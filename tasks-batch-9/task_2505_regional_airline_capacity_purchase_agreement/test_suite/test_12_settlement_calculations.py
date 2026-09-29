"""Money and metric arithmetic with every intermediate figure pinned.

Scorecard metrics and their caps, the brand-exposure filter and its ceiling, the
pass-through waterfall, the block-hour aggregate, and the provisional variable basis.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers.assertions import (
    assert_block_hours,
    assert_is_null,
    assert_money,
    assert_percentage,
    assert_status,
)
from test_helpers.constants import BRAND_PENALTY_CAP_USD
from test_helpers.factories import (
    make_agreement_payload,
    make_completion_payload,
    make_invoice_payload,
    make_reconcile_payload,
)
from test_helpers.fixtures import (
    acknowledge_brand_audit,
    add_leg,
    advance_remediation,
    build_active_agreement,
    build_open_cycle,
    cancel_leg,
    close_brand_audit,
    close_cycle,
    complete_leg,
    create_brand_audit,
    create_cycle,
    cycle_version,
    file_pass_through_actual,
    open_cycle,
    open_pass_through,
    read_brand_audit,
    read_cycle,
    read_invoice,
    read_leg,
    scorecard_for_cycle,
)
from test_helpers.test_users import ADMIN_HEADERS, SCHEDULER_HEADERS

FIXED_COMPONENT_WITH_ONE_OWNED_TAIL_USD = 312000.00


def _build_empty_month_on_a_tailless_agreement(api, station_code):
    """An open month of no bought departures on an agreement that owns no aeroplane."""
    scenario = build_active_agreement(
        api,
        agreement_payload=make_agreement_payload(),
        station_code=station_code,
        pilots_required_per_aircraft=1,
        aircraft_allocation_cap=1,
    )
    cycle = create_cycle(api, scenario.agreement_id, cycle_month="2026-09", published_departures=0)
    return scenario, open_cycle(api, cycle["id"])


class TestBagRateAndRevenueShareCeiling:
    """A flawless completion and punctuality month still loses points on baggage."""

    def test_the_bag_rate_costs_two_points_and_the_revenue_cap_sets_the_payout(self, api):
        """Six mishandled bags per thousand is past the band floor of five and a half.

        PRD 3.7: "**Mishandled bags**, published as `mishandled_bags_per_1000`, is one
        thousand multiplied by `mishandled_bags_total` divided by `enplaned_bags_total`,
        rounded half-up to two decimals, with a pinned convention of 0.00 when
        `enplaned_bags_total` is 0 — a month that carried no bags mishandled none."

        PRD 3.7: "When `gross_performance_usd` is zero or positive, `penalty_usd` is 0.00
        and `incentive_usd` is the smallest of three quantities: `gross_performance_usd`
        itself, the agreement's `incentive_pool_cap_usd`, and a revenue-share ceiling equal
        to one twentieth of the month's own revenue, rounded half-up to two decimals."

        Design: Corner/calculations/bag_rate_and_revenue_cap_from_two_completed_legs
        """
        scenario = build_open_cycle(
            api,
            agreement_payload=make_agreement_payload(),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
            line_qualified_pilots=1,
            tail_numbers=["N3301RG"],
            cycle_month="2026-09",
            published_departures=2,
        )
        outbound = add_leg(
            api,
            scenario,
            flight_number="SM6801",
            origin="MKE",
            destination="ORD",
            scheduled_departure_utc="2026-09-02T08:00:00Z",
            scheduled_arrival_utc="2026-09-02T09:00:00Z",
            planned_block_hours=1.000,
        )
        inbound = add_leg(
            api,
            scenario,
            flight_number="SM6802",
            origin="ORD",
            destination="MKE",
            scheduled_departure_utc="2026-09-02T11:00:00Z",
            scheduled_arrival_utc="2026-09-02T12:00:00Z",
            planned_block_hours=1.000,
        )
        complete_leg(
            api,
            outbound["id"],
            make_completion_payload(
                actual_block_hours=1.000,
                actual_arrival_utc="2026-09-02T09:05:00Z",
                enplaned_bags=300,
                mishandled_bags=1,
            ),
        )
        complete_leg(
            api,
            inbound["id"],
            make_completion_payload(
                actual_block_hours=1.000,
                actual_arrival_utc="2026-09-02T12:05:00Z",
                enplaned_bags=200,
                mishandled_bags=2,
            ),
        )

        closed = validate_success(
            api.close_schedule_cycle(scenario.cycle_id, headers=SCHEDULER_HEADERS)
        )

        assert_status(closed, "CLOSED")
        assert closed["enplaned_bags_total"] == 500
        assert closed["mishandled_bags_total"] == 3
        assert closed["on_time_leg_count"] == 2
        assert closed["recorded_completed_legs"] == 2
        assert_block_hours(closed["credited_block_hours"], 2.000, "credited block hours")

        cards, meta = validate_paginated(
            api.list_scorecards(headers=ADMIN_HEADERS, params={"cycle_id": scenario.cycle_id})
        )
        assert meta["total_count"] == 1
        scorecard = cards[0]
        assert_percentage(scorecard["completion_factor_pct"], 100.00, "completion factor")
        assert_percentage(scorecard["on_time_arrival_pct"], 100.00, "on-time arrival")
        assert_percentage(scorecard["mishandled_bags_per_1000"], 6.00, "mishandled bags per 1000")

        assert scorecard["completion_factor_points"] == 3
        assert scorecard["on_time_points"] == 2
        assert scorecard["bag_points"] == -2
        assert scorecard["performance_points"] == 3
        assert_money(scorecard["gross_performance_usd"], 36000.00, "gross performance")
        assert_money(scorecard["incentive_usd"], 15777.08, "incentive under the revenue ceiling")
        assert_money(scorecard["penalty_usd"], 0.00, "penalty")
        assert_money(scorecard["brand_penalty_usd"], 0.00, "brand penalty")


class TestBrandExposureFilter:
    """Leaving either dimension is enough to drop an audit out of the exposure set."""

    def test_a_verified_and_a_closed_audit_cost_nothing_while_two_others_still_bite(self, api):
        """The filter is a conjunction, so one dimension can carry the whole exemption.

        PRD 3.7: "An audit is exposed when its base belongs to the same agreement as the
        month being scored, its `finding_status` is `OPEN` or `ACKNOWLEDGED`, and its
        `remediation_status` is `NOT_STARTED` or `IN_PROGRESS`."

        Design: Corner/calculations/brand_penalty_excludes_closed_or_verified_audits
        """
        scenario, cycle = _build_empty_month_on_a_tailless_agreement(api, "MKE")

        exposed_major = create_brand_audit(
            api, scenario.crew_base_id, audit_scope="UNIFORM", findings_count=2, severity="MAJOR"
        )
        verified_minor = create_brand_audit(
            api,
            scenario.crew_base_id,
            audit_scope="CABIN_PRODUCT",
            findings_count=3,
            severity="MINOR",
        )
        closed_critical = create_brand_audit(
            api, scenario.crew_base_id, audit_scope="LIVERY", findings_count=1, severity="CRITICAL"
        )
        in_progress_major = create_brand_audit(
            api,
            scenario.crew_base_id,
            audit_scope="SERVICE_SCRIPT",
            findings_count=1,
            severity="MAJOR",
        )

        advance_remediation(api, verified_minor["id"], "IN_PROGRESS")
        advance_remediation(api, verified_minor["id"], "VERIFIED", evidence_ref="EV-A2")

        acknowledge_brand_audit(api, closed_critical["id"])
        advance_remediation(api, closed_critical["id"], "IN_PROGRESS")
        advance_remediation(api, closed_critical["id"], "VERIFIED", evidence_ref="EV-A3")
        close_brand_audit(api, closed_critical["id"])

        acknowledge_brand_audit(api, in_progress_major["id"])
        advance_remediation(api, in_progress_major["id"], "IN_PROGRESS")

        close_cycle(api, cycle["id"])

        exempt_by_remediation = read_brand_audit(api, verified_minor["id"])
        assert_status(exempt_by_remediation, "OPEN", field="finding_status")
        assert_status(exempt_by_remediation, "VERIFIED", field="remediation_status")
        assert_status(
            read_brand_audit(api, closed_critical["id"]), "CLOSED", field="finding_status"
        )
        still_exposed = read_brand_audit(api, in_progress_major["id"])
        assert_status(still_exposed, "ACKNOWLEDGED", field="finding_status")
        assert_status(still_exposed, "IN_PROGRESS", field="remediation_status")

        cards, meta = validate_paginated(
            api.list_scorecards(headers=ADMIN_HEADERS, params={"cycle_id": cycle["id"]})
        )
        assert meta["total_count"] == 1
        scorecard = cards[0]
        assert_money(
            scorecard["brand_penalty_usd"],
            7500.00,
            "two major findings plus one, at 2,500.00 apiece",
        )
        assert exposed_major["severity"] == "MAJOR"

        assert_percentage(scorecard["completion_factor_pct"], 100.00, "completion factor")
        assert_percentage(scorecard["on_time_arrival_pct"], 100.00, "on-time arrival")
        assert_percentage(scorecard["mishandled_bags_per_1000"], 0.00, "mishandled bags per 1000")
        assert scorecard["performance_points"] == 6
        assert_money(scorecard["incentive_usd"], 12500.00, "incentive under the revenue ceiling")


class TestBrandPenaltyCeiling:
    """Past the ceiling the severity weights stop mattering."""

    def test_thirty_thousand_of_raw_exposure_is_recorded_at_the_ceiling(self, api):
        """The brand penalty is its own ledger line, not a deduction from the incentive.

        PRD 3.7: "`brand_penalty_usd` is the smaller of that sum rounded half-up to two
        decimals and a hard ceiling of 25,000.00 US dollars per month."

        Design: Corner/calculations/brand_penalty_clipped_at_cap_constant
        """
        scenario, cycle = _build_empty_month_on_a_tailless_agreement(api, "MKE")
        audit = create_brand_audit(
            api, scenario.crew_base_id, audit_scope="LIVERY", findings_count=4, severity="CRITICAL"
        )

        close_cycle(api, cycle["id"])

        scorecard = scorecard_for_cycle(api, cycle["id"])
        assert_money(
            scorecard["brand_penalty_usd"], BRAND_PENALTY_CAP_USD, "brand penalty at its ceiling"
        )

        standing = read_brand_audit(api, audit["id"])
        assert standing["findings_count"] == 4
        assert standing["severity"] == "CRITICAL"
        assert_status(standing, "OPEN", field="finding_status")
        assert_status(standing, "NOT_STARTED", field="remediation_status")

        assert_money(scorecard["incentive_usd"], 12500.00, "incentive under the revenue ceiling")
        assert_money(scorecard["penalty_usd"], 0.00, "performance penalty")


class TestRejectedPassThroughLeavesBothLedgers:
    """Only reconciled claims form the settlement base, and rejection drops the estimate too."""

    def test_an_approved_claim_settles_with_its_fee_while_the_rejected_one_vanishes(self, api):
        """The rejected claim keeps its variance but contributes to neither ledger.

        PRD 3.6: "Rejection moves the claim to `REJECTED` instead, leaves
        `allowed_amount_usd` null, and drops the claim out of both the month's
        `estimated_passthrough_total_usd` and the settlement base described next; both of
        those month figures are recomputed on the spot."

        PRD 3.6: "Step two forms the **base pass-through total**: the sum of
        `allowed_amount_usd` over the month's claims whose status is `RECONCILED`, taken in
        ascending `created_at` order over addends that are already carried at two decimals,
        so the sum is exact."

        Design: Corner/calculations/rejected_passthrough_actual_excluded_from_settlement
        """
        _scenario, cycle = _build_empty_month_on_a_tailless_agreement(api, "MKE")

        fees = open_pass_through(
            api, cycle["id"], category="AIRPORT_FEES", estimated_amount_usd=10000.00
        )
        insurance = open_pass_through(
            api, cycle["id"], category="INSURANCE", estimated_amount_usd=5000.00
        )
        file_pass_through_actual(api, fees["id"], 10500.00, supporting_doc_ref="DOC-C1")
        file_pass_through_actual(api, insurance["id"], 9000.00, supporting_doc_ref="DOC-C2")

        approved = validate_success(
            api.reconcile_pass_through(
                fees["id"], make_reconcile_payload("APPROVE"), headers=ADMIN_HEADERS
            )
        )
        rejected = validate_success(
            api.reconcile_pass_through(
                insurance["id"], make_reconcile_payload("REJECT"), headers=ADMIN_HEADERS
            )
        )

        assert_status(approved, "RECONCILED")
        assert_money(
            approved["allowed_amount_usd"], 10500.00, "the actual, under the ten-percent ceiling"
        )
        assert_money(approved["variance_usd"], 500.00, "approved variance")
        assert approved["reconciled_by_user_id"] == "admin-1"

        assert_status(rejected, "REJECTED")
        assert_is_null(rejected, "allowed_amount_usd")
        assert_money(rejected["variance_usd"], 4000.00, "rejected variance")

        month = read_cycle(api, cycle["id"])
        assert_money(
            month["passthrough_settlement_usd"],
            10815.00,
            "the base total plus its three-percent administrative fee",
        )
        assert_money(
            month["estimated_passthrough_total_usd"],
            10000.00,
            "the rejected claim's estimate leaves the estimate ledger",
        )


class TestBlockHourAggregateCountsCompletedLegsOnly:
    """The aggregate is keyed on leg status, not on the hours a leg was published with."""

    def test_a_cancelled_and_a_scheduled_leg_add_nothing_to_the_credited_hours(self, api):
        """Four generous planned hours and two more contribute exactly zero.

        PRD 3.4: "Completion also rolls the month's counters forward:
        `recorded_completed_legs` rises by 1, `open_leg_count` falls by 1,
        `credited_block_hours` takes on the leg's `actual_block_hours` in addition to what
        it held, `enplaned_bags_total` and `mishandled_bags_total` absorb the two reported
        bag counts, and `on_time_leg_count` rises by 1 only when `on_time` came out true."

        Design: Corner/calculations/cycle_block_hour_aggregate_counts_completed_legs_only
        """
        scenario = build_open_cycle(
            api,
            agreement_payload=make_agreement_payload(),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
            line_qualified_pilots=1,
            tail_numbers=["N3401RG"],
            cycle_month="2026-09",
            published_departures=3,
        )
        flown = add_leg(
            api,
            scenario,
            flight_number="SM6901",
            origin="MKE",
            destination="ORD",
            scheduled_departure_utc="2026-09-02T08:00:00Z",
            scheduled_arrival_utc="2026-09-02T09:15:00Z",
            planned_block_hours=1.250,
        )
        dropped = add_leg(
            api,
            scenario,
            flight_number="SM6902",
            origin="ORD",
            destination="DEN",
            scheduled_departure_utc="2026-09-03T08:00:00Z",
            scheduled_arrival_utc="2026-09-03T12:00:00Z",
            planned_block_hours=4.000,
        )
        add_leg(
            api,
            scenario,
            flight_number="SM6903",
            origin="DEN",
            destination="MKE",
            scheduled_departure_utc="2026-09-04T08:00:00Z",
            scheduled_arrival_utc="2026-09-04T10:00:00Z",
            planned_block_hours=2.000,
        )

        complete_leg(
            api,
            flown["id"],
            make_completion_payload(
                actual_block_hours=1.250,
                actual_arrival_utc="2026-09-02T09:29:00Z",
                enplaned_bags=100,
                mishandled_bags=0,
            ),
        )
        cancel_leg(api, dropped["id"], cause_code="MAINTENANCE")

        month = read_cycle(api, scenario.cycle_id)
        assert_block_hours(month["credited_block_hours"], 1.250, "credited block hours")
        assert month["recorded_completed_legs"] == 1
        assert month["open_leg_count"] == 1
        assert month["cancelled_controllable_count"] == 1
        assert month["metric_completed_departures"] == 2
        assert month["departure_ledger_total"] == 3
        assert month["on_time_leg_count"] == 1

        standing = read_leg(api, flown["id"])
        assert standing["on_time"] is True, (
            "fourteen minutes late is inside the inclusive grace allowance"
        )
        assert_money(standing["leg_variable_payment_usd"], 2133.44, "leg variable payment")


class TestProvisionalInvoicePaysPublishedPlan:
    """The provisional bill pays flying that has not happened yet and then freezes."""

    def test_the_planned_basis_pays_a_scheduled_leg_and_a_later_cancel_cannot_reprice_it(
        self, api
    ):
        """Both legs are paid on plan, and the cancellation moves only the month.

        PRD 3.8: "On a `PROVISIONAL` invoice the included legs are the month's legs whose
        status is `SCHEDULED` or `COMPLETED` and the hours used are each leg's
        `planned_block_hours`, so still-open flying is paid for in advance on its published
        plan."

        PRD 3.8: "Creating an invoice computes every component once, at creation, from the
        state of the world at that instant; no component and no total is ever recomputed
        afterwards."

        Design: Corner/calculations/provisional_invoice_pays_scheduled_exposure_and_freezes_it
        """
        scenario = build_open_cycle(
            api,
            agreement_payload=make_agreement_payload(),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
            line_qualified_pilots=1,
            tail_numbers=["N3501RG"],
            cycle_month="2026-09",
            published_departures=2,
        )
        flown = add_leg(
            api,
            scenario,
            flight_number="SM7001",
            origin="MKE",
            destination="DEN",
            scheduled_departure_utc="2026-09-02T08:00:00Z",
            scheduled_arrival_utc="2026-09-02T10:00:00Z",
            planned_block_hours=2.000,
        )
        pending = add_leg(
            api,
            scenario,
            flight_number="SM7002",
            origin="DEN",
            destination="MKE",
            scheduled_departure_utc="2026-09-02T11:00:00Z",
            scheduled_arrival_utc="2026-09-02T12:30:00Z",
            planned_block_hours=1.500,
        )
        complete_leg(
            api,
            flown["id"],
            make_completion_payload(
                actual_block_hours=1.000,
                actual_arrival_utc="2026-09-02T10:05:00Z",
                enplaned_bags=120,
                mishandled_bags=0,
            ),
        )
        open_pass_through(
            api, scenario.cycle_id, category="AIRPORT_FEES", estimated_amount_usd=5000.00
        )

        invoice = validate_success(
            api.create_invoice(
                scenario.cycle_id,
                make_invoice_payload("PROVISIONAL", cycle_version(api, scenario.cycle_id)),
                headers=ADMIN_HEADERS,
            ),
            201,
        )

        assert_status(invoice, "DRAFT")
        assert invoice["variant"] == "PROVISIONAL"
        assert invoice["ownership_aircraft_count"] == 1
        assert_money(
            invoice["fixed_component_usd"],
            FIXED_COMPONENT_WITH_ONE_OWNED_TAIL_USD,
            "fixed component",
        )
        assert_money(
            invoice["variable_component_usd"],
            5717.63,
            "both legs paid on their published plan",
        )
        assert_money(invoice["passthrough_component_usd"], 5000.00, "pass-through component")
        assert_money(invoice["incentive_component_usd"], 0.00, "incentive component")
        assert_money(invoice["penalty_component_usd"], 0.00, "penalty component")
        assert_money(invoice["brand_penalty_component_usd"], 0.00, "brand penalty component")
        assert_money(invoice["total_usd"], 322717.63, "provisional total")

        cancel_leg(api, pending["id"], cause_code="CREW_UNAVAILABLE")

        month = read_cycle(api, scenario.cycle_id)
        assert month["open_leg_count"] == 0
        assert month["cancelled_controllable_count"] == 1

        frozen = read_invoice(api, invoice["id"])
        assert_money(frozen["variable_component_usd"], 5717.63, "frozen variable component")
        assert_money(frozen["total_usd"], 322717.63, "frozen total")
