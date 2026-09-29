"""Exact boundaries: the last admitted value and the first refused one.

Two limits in this PRD are stated as inclusive and are easy to implement one step out.
Cooling capacity permits equality, so a row cooled for exactly 21.120 kW must accept a
load that lands on 21.120 and refuse the next kilowatt. A work segment of zero whole
minutes is legal, so it must complete the ticket while billing nothing, consuming no
bundle minutes and appending no ledger row — whereas an inverted interval is not legal
at all. Both boundaries are walked from the admitted side to the refused side.
"""

from datetime import datetime
from typing import Any

from test_helpers import (
    ApiErrorId,
    ENGINEER_1,
    ENGINEER_2,
    validate_error,
    validate_success,
)
from test_helpers import assertions as ax, constants as k, factories as f, fixtures as fx


# ---------------------------------------------------------------------------
# module-local helpers
# ---------------------------------------------------------------------------


def _parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating the `Z` suffix and any number of
    fractional digits, so an assertion compares instants and not spellings."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 timestamp, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_same_instant(actual: Any, expected: str, label: str) -> None:
    assert _parse_instant(actual) == _parse_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def _energize(api, circuit_id: str, row_id: str):
    return api.energize_circuit(
        circuit_id, {"expected_row_version": fx.row_version(api, row_id)}, ENGINEER_1
    )


# --- scenery for the cooling boundary --------------------------------------

ROW_COOLED_TO_21_120 = {
    "hall_code": "HC",
    "row_code": "R1",
    "cabinet_slot_count": 8,
    "design_density_kw_per_cabinet": 25.0,
    "max_row_power_kw": 200.0,
    "cooling_capacity_kw": 21.120,
    "escort_slot_count": 1,
    "decommission_flag": False,
}

CONTRACT_30_KW = {
    "billing_mode": "COMMITTED_ONLY",
    "committed_cabinet_count": 1,
    "power_commit_kw": 30.0,
    "committed_bandwidth_mbps": 1000,
    "cross_connect_cap": 4,
    "term_start_date": "2026-07-01T00:00:00Z",
    "term_end_date": "2027-06-30T00:00:00Z",
    "committed_cage_sqft": 0,
    "redundancy_requirement": "N",
    "cross_connect_allowance": 0,
    "remote_hands_included_minutes": 0,
}


def _setup_three_feeds_against_a_cooling_ceiling(api):
    """One `INSTALLED` cabinet rated 25.0 kW in a row cooled for exactly 21.120 kW,
    carrying three `APPROVED` primary feeds: 50 A (9.600 kW), 60 A (11.520 kW) and
    25 A (4.800 kW). The first two sum to exactly the cooling capacity; the third
    would take the row one step past it.
    """
    scenario = fx.setup_installed_cabinet(
        api,
        row=ROW_COOLED_TO_21_120,
        contract=CONTRACT_30_KW,
        cabinet={"cabinet_code": "C01", "rated_power_kw": 25.0},
    )
    for circuit_code, breaker_amps in (("A-1", 50), ("A-2", 60), ("A-3", 25)):
        fx.add_approved_circuit(
            api,
            scenario,
            circuit_code=circuit_code,
            feed_side="A",
            redundancy_role="PRIMARY",
            breaker_amps=breaker_amps,
            volts=240,
            phase="SINGLE",
        )
    return scenario


# --- scenery for the labour boundary ---------------------------------------

CONTRACT_ONE_INCLUDED_INCREMENT = {
    "billing_mode": "COMMITTED_ONLY",
    "committed_cabinet_count": 1,
    "power_commit_kw": 20.0,
    "committed_bandwidth_mbps": 1000,
    "cross_connect_cap": 4,
    "term_start_date": "2026-07-01T00:00:00Z",
    "term_end_date": "2027-06-30T00:00:00Z",
    "committed_cage_sqft": 0,
    "redundancy_requirement": "N",
    "cross_connect_allowance": 0,
    "remote_hands_included_minutes": 15,
}


def _setup_dispatched_critical_ticket(api):
    """A `CRITICAL` ticket on a contract holding exactly one included 15-minute
    increment, authorized by a second contact and dispatched by a second engineer at
    the default clock."""
    return fx.setup_dispatched_ticket(
        api,
        contract=CONTRACT_ONE_INCLUDED_INCREMENT,
        cabinet={"cabinet_code": "C01"},
        severity="CRITICAL",
    )


# ---------------------------------------------------------------------------
# Cooling capacity: equality is admitted, one step beyond is refused
# ---------------------------------------------------------------------------


class TestCoolingCapacityBoundary:
    def test_first_energization_below_the_alert_threshold_leaves_the_row_open(self, api):
        """PRD §3.2: "Otherwise, if `cooling_load_kw` has reached or passed 90 percent of `cooling_capacity_kw` the row is `COOLING_CONSTRAINED`."
        PRD §3.4: "For a `PRIMARY` circuit, `allocated_kw` is the lesser of its derated capacity and the host cabinet's `rated_power_kw` — the cabinet nameplate clamps what the floor will bill for, and the clamp is applied to the already-rounded derated figure — while `cooling_contribution_kw` is the full derated capacity, because heat is not clamped by a nameplate."

        Design: Difficulty/boundary_precision_check/cooling_load_at_exact_capacity_is_admitted_one_step_beyond_is_refused
        """
        scenario = _setup_three_feeds_against_a_cooling_ceiling(api)

        validate_success(_energize(api, scenario.circuits[0]["id"], scenario.row_id))

        first = fx.read_circuit(api, scenario.circuits[0]["id"])
        ax.assert_circuit_power(
            first,
            status="ENERGIZED",
            derated_kw=9.600,
            allocated_kw=9.600,
            cooling_contribution_kw=9.600,
        )
        row = fx.read_row(api, scenario.row_id)
        ax.assert_row_capacity_view(
            row,
            allocated_power_kw=9.600,
            cooling_load_kw=9.600,
            energized_cabinet_count=1,
            row_status="OPEN",
        )

    def test_second_energization_landing_exactly_on_cooling_capacity_is_admitted(self, api):
        """PRD §2.5: "The projected row `cooling_load_kw` after the energization is less than or equal to the row's `cooling_capacity_kw`, otherwise `ERR_COOLING_CAPACITY_EXCEEDED` (422)."
        PRD §3.4: "Four numeric projections follow, each computed as though this circuit were already energized, and each permitting equality — only a strictly greater projection is refused."

        Design: Difficulty/boundary_precision_check/cooling_load_at_exact_capacity_is_admitted_one_step_beyond_is_refused
        """
        scenario = _setup_three_feeds_against_a_cooling_ceiling(api)
        fx.energize_circuit(api, scenario.circuits[0]["id"], scenario.row_id)

        validate_success(_energize(api, scenario.circuits[1]["id"], scenario.row_id))

        second = fx.read_circuit(api, scenario.circuits[1]["id"])
        ax.assert_circuit_power(
            second,
            status="ENERGIZED",
            derated_kw=11.520,
            allocated_kw=11.520,
            cooling_contribution_kw=11.520,
        )
        row = fx.read_row(api, scenario.row_id)
        ax.assert_kw_equals(row["cooling_load_kw"], 21.120, "row.cooling_load_kw at capacity")
        ax.assert_kw_equals(
            row["cooling_load_kw"], row["cooling_capacity_kw"], "cooling load against capacity"
        )

    def test_the_row_at_exact_capacity_reports_cooling_constrained_and_a_clamped_ceiling(
        self, api
    ):
        """PRD §3.2: "`effective_ceiling_kw` is the smallest of three numbers: the busway limit `max_row_power_kw`, the density ceiling just derived, and the cooling capacity."
        PRD §3.2: "The **nameplate view**, `stranded_nameplate_kw`, is the effective ceiling minus `allocated_power_kw`, rounded to three decimals: it charges the row for every breaker plate that has been energized, so a lightly loaded cabinet with a large breaker strands nothing at all."
        PRD §3.2: "Otherwise, if `cooling_load_kw` has reached or passed 90 percent of `cooling_capacity_kw` the row is `COOLING_CONSTRAINED`."

        Design: Difficulty/boundary_precision_check/cooling_load_at_exact_capacity_is_admitted_one_step_beyond_is_refused
        """
        scenario = _setup_three_feeds_against_a_cooling_ceiling(api)
        fx.energize_circuit(api, scenario.circuits[0]["id"], scenario.row_id)
        fx.energize_circuit(api, scenario.circuits[1]["id"], scenario.row_id)

        row = fx.read_row(api, scenario.row_id)
        ax.assert_floor_row(row)
        ax.assert_row_capacity_view(
            row,
            occupied_slot_count=1,
            density_ceiling_kw=25.000,
            effective_ceiling_kw=21.120,
            allocated_power_kw=21.120,
            cooling_load_kw=21.120,
            energized_cabinet_count=1,
            stranded_nameplate_kw=0.000,
            row_status="COOLING_CONSTRAINED",
        )

    def test_third_energization_one_step_beyond_cooling_capacity_is_refused(self, api):
        """PRD §2.5: "The projected row `cooling_load_kw` after the energization is less than or equal to the row's `cooling_capacity_kw`, otherwise `ERR_COOLING_CAPACITY_EXCEEDED` (422)."
        PRD §3.2: "Energization applies a narrower version of the same idea: there the only row-level bar is `decommission_flag` being true, so a `DENSITY_CAPPED` row still lets the cabinets already installed in it energize their approved circuits, subject to the numeric gates of §3.4."

        Design: Difficulty/boundary_precision_check/cooling_load_at_exact_capacity_is_admitted_one_step_beyond_is_refused
        """
        scenario = _setup_three_feeds_against_a_cooling_ceiling(api)
        fx.energize_circuit(api, scenario.circuits[0]["id"], scenario.row_id)
        fx.energize_circuit(api, scenario.circuits[1]["id"], scenario.row_id)

        refused = _energize(api, scenario.circuits[2]["id"], scenario.row_id)
        validate_error(refused, ApiErrorId.ERR_COOLING_CAPACITY_EXCEEDED)

        third = fx.read_circuit(api, scenario.circuits[2]["id"])
        ax.assert_circuit_power(
            third,
            status="APPROVED",
            derated_kw=4.800,
            allocated_kw=0.000,
            cooling_contribution_kw=0.000,
        )
        row = fx.read_row(api, scenario.row_id)
        ax.assert_row_capacity_view(
            row,
            allocated_power_kw=21.120,
            cooling_load_kw=21.120,
            energized_cabinet_count=1,
        )

    def test_contract_rollup_reflects_only_the_two_admitted_feeds(self, api):
        """PRD §3.4: "`provisioned_power_kw` is the sum of `allocated_kw` over circuits that are both `ENERGIZED` and `PRIMARY` on cabinets whose `contract_id` is this contract, rounded to three decimals."
        PRD §3.4: "`stranded_commit_kw` is the contracted commitment minus that provisioned figure, floored at zero so an over-provisioned contract reports 0.000 rather than a negative number, rounded to three decimals."
        PRD §3.4: "`commit_utilization_pct` is the provisioned figure divided by `power_commit_kw`, multiplied by 100 and rounded to one decimal place."

        Design: Difficulty/boundary_precision_check/cooling_load_at_exact_capacity_is_admitted_one_step_beyond_is_refused
        """
        scenario = _setup_three_feeds_against_a_cooling_ceiling(api)
        fx.energize_circuit(api, scenario.circuits[0]["id"], scenario.row_id)
        fx.energize_circuit(api, scenario.circuits[1]["id"], scenario.row_id)
        validate_error(
            _energize(api, scenario.circuits[2]["id"], scenario.row_id),
            ApiErrorId.ERR_COOLING_CAPACITY_EXCEEDED,
        )

        contract = fx.read_contract(api, scenario.contract_id)
        ax.assert_contract_power_rollup(
            contract,
            provisioned_power_kw=21.120,
            stranded_commit_kw=8.880,
            commit_utilization_pct=70.4,
        )


# ---------------------------------------------------------------------------
# A zero-length work segment: legal, and it bills nothing
# ---------------------------------------------------------------------------


class TestZeroLengthWorkSegment:
    def test_dispatch_within_the_critical_response_target_meets_the_commitment(self, api):
        """PRD §3.6: "`response_deadline_at` is `authorized_at` advanced by 30 minutes for a `CRITICAL` ticket, by 120 minutes for a `HIGH` ticket, and by 480 minutes — eight hours — for a `STANDARD` ticket."
        PRD §3.6: "On success `dispatched_at` is stamped from the logical clock and `sla_breached` is set true only when `dispatched_at` is strictly later than `response_deadline_at`; a dispatch landing exactly on the deadline instant has met the commitment, not breached it."

        Design: Difficulty/boundary_precision_check/zero_length_work_segment_bills_nothing_and_consumes_no_bundle
        """
        scenario = _setup_dispatched_critical_ticket(api)

        ticket = fx.read_ticket(api, scenario.ticket["id"])
        ax.assert_remote_hands_ticket(ticket)
        assert ticket["execution_state"] == "DISPATCHED"
        assert_same_instant(ticket["authorized_at"], k.DEFAULT_CLOCK, "ticket.authorized_at")
        assert_same_instant(
            ticket["response_deadline_at"],
            "2026-08-01T00:30:00Z",
            "ticket.response_deadline_at for a CRITICAL ticket",
        )
        ax.assert_ticket_labor(ticket, sla_breached=False)

    def test_zero_length_segment_completes_the_ticket_and_bills_no_increments(self, api):
        """PRD §3.6: "The list must be non-empty, otherwise `ERR_INVALID_REQUEST`, and each segment's `ended_at` must be at or after its `started_at`, otherwise `ERR_BILLING_PERIOD_INVALID`; a zero-length segment is legal and simply bills nothing."
        PRD §3.6: "For each segment, the raw duration is the whole minutes between its `started_at` and its `ended_at`, discarding any remaining seconds; a segment of zero whole minutes contributes zero increments, and any other segment contributes its raw minutes divided by 15 and rounded **up** to the next whole increment."
        PRD §3.6: "`billed_minutes` is `billable_increments` multiplied by 15."
        PRD §3.6: "The ticket's `completed_at` is stamped, `execution_state` becomes `COMPLETED`, the contract's `billed_total_usd` is refreshed, and both the ticket's and the contract's `version` increment."

        Design: Difficulty/boundary_precision_check/zero_length_work_segment_bills_nothing_and_consumes_no_bundle
        """
        scenario = _setup_dispatched_critical_ticket(api)

        completed = validate_success(
            api.complete_ticket(
                scenario.ticket["id"],
                f.complete_ticket_payload(
                    f.work_segment("2026-08-01T09:00:00Z", "2026-08-01T09:00:00Z")
                ),
                ENGINEER_2,
            )
        )

        assert completed["execution_state"] == "COMPLETED", (
            f"a zero-length segment still completes the work, got {completed['execution_state']}"
        )
        assert_same_instant(completed["completed_at"], k.DEFAULT_CLOCK, "ticket.completed_at")
        ax.assert_ticket_labor(
            completed,
            billable_increments=0,
            billed_minutes=0,
            included_increments_applied=0,
            labor_charge_usd=0.00,
        )
        assert len(completed["work_segments"]) == 1, (
            f"the submitted segment is stored, got {completed['work_segments']}"
        )

    def test_zero_length_completion_appends_no_ledger_row_and_consumes_no_bundle(self, api):
        """PRD §3.6: "The contract's `remote_hands_remaining_minutes` is reduced by `included_increments_applied` multiplied by 15."
        PRD §3.6: "When `labor_charge_usd` is greater than zero, an invoice line of `line_type` `REMOTE_HANDS` is appended carrying that amount, a `quantity` equal to `billable_increments` minus `included_increments_applied`, and `included_minutes_consumed` equal to the absorbed increments multiplied by 15."
        PRD §3.6: "When that line exists *and* `sla_breached` is true, a second line of `line_type` `SLA_CREDIT` is appended for the negative of 25 percent of `labor_charge_usd`, rounded to two decimals — a breach with no billable charge produces no credit, because there is nothing to credit against."
        PRD §3.1: "A newly created contract opens in `DRAFT` with `credit_hold` false, `remote_hands_remaining_minutes` initialised to `remote_hands_included_minutes`, every rollup field (`provisioned_power_kw`, `stranded_commit_kw`, `commit_utilization_pct`, `active_cross_connect_count`, `billed_total_usd`, `cross_connect_billed_usd`) at zero and `last_closed_period_end` unset."

        Design: Difficulty/boundary_precision_check/zero_length_work_segment_bills_nothing_and_consumes_no_bundle
        """
        scenario = _setup_dispatched_critical_ticket(api)

        fx.complete_ticket(
            api,
            scenario.ticket["id"],
            f.work_segment("2026-08-01T09:00:00Z", "2026-08-01T09:00:00Z"),
        )

        lines = fx.invoice_lines(api, scenario.contract_id)
        assert lines == [], (
            f"nothing was billable, so the ledger stays empty, got {[l['line_type'] for l in lines]}"
        )
        contract = fx.read_contract(api, scenario.contract_id)
        ax.assert_contract_billing_rollup(
            contract, remote_hands_remaining_minutes=15, billed_total_usd=0.00
        )

    def test_replaying_the_completion_is_refused_and_changes_nothing(self, api):
        """PRD §2.5: "The requested `to_state` is reachable from the entity's current state per §3, otherwise `ERR_INVALID_STATE` (409)."
        PRD §2.5: "This includes terminal-state lockdown — `TERMINATED`, `RELEASED`, `REMOVED`, `DECOMMISSIONED`, `ABORTED`, `CLOSED`, `CANCELLED` and `CHECKED_OUT` accept no further transitions — and the rejection of a replayed trigger."
        PRD §3.6: "Completion is also exclusive to a `ProvisioningEngineer`, requires the ticket to be `DISPATCHED` with `authorization_state` still `AUTHORIZED` (`ERR_TICKET_NOT_AUTHORIZED` otherwise), and carries `work_segments`, the labour actually performed."

        Design: Difficulty/boundary_precision_check/zero_length_work_segment_bills_nothing_and_consumes_no_bundle
        """
        scenario = _setup_dispatched_critical_ticket(api)
        fx.complete_ticket(
            api,
            scenario.ticket["id"],
            f.work_segment("2026-08-01T09:00:00Z", "2026-08-01T09:00:00Z"),
        )
        after_first = fx.read_ticket(api, scenario.ticket["id"])

        replay = api.complete_ticket(
            scenario.ticket["id"],
            f.complete_ticket_payload(
                f.work_segment("2026-08-01T10:00:00Z", "2026-08-01T10:20:00Z")
            ),
            ENGINEER_2,
        )
        validate_error(replay, ApiErrorId.ERR_INVALID_STATE)

        unchanged = fx.read_ticket(api, scenario.ticket["id"])
        ax.assert_timestamps_unchanged(after_first, unchanged, "ticket")
        ax.assert_ticket_labor(
            unchanged,
            billable_increments=0,
            billed_minutes=0,
            included_increments_applied=0,
            labor_charge_usd=0.00,
        )
        assert len(unchanged["work_segments"]) == 1, (
            "the replayed segments were not appended"
        )
        assert fx.invoice_lines(api, scenario.contract_id) == []
        ax.assert_contract_billing_rollup(
            fx.read_contract(api, scenario.contract_id),
            remote_hands_remaining_minutes=15,
            billed_total_usd=0.00,
        )

    def test_an_inverted_work_segment_is_refused_where_a_zero_length_one_is_not(self, api):
        """PRD §2.5: "`period_end` is strictly after `period_start`, a metered interval's `interval_end` is after its `interval_start`, and every work segment's `ended_at` is greater than or equal to its `started_at`, otherwise `ERR_BILLING_PERIOD_INVALID` (422)."
        PRD §2.5: "Zero-length work segments are legal and bill nothing; inverted intervals are not legal."

        Design: Difficulty/boundary_precision_check/zero_length_work_segment_bills_nothing_and_consumes_no_bundle
        """
        scenario = _setup_dispatched_critical_ticket(api)
        before = fx.read_ticket(api, scenario.ticket["id"])

        refused = api.complete_ticket(
            scenario.ticket["id"],
            f.complete_ticket_payload(
                f.work_segment("2026-08-01T09:20:00Z", "2026-08-01T09:00:00Z")
            ),
            ENGINEER_2,
        )
        validate_error(refused, ApiErrorId.ERR_BILLING_PERIOD_INVALID)

        unchanged = fx.read_ticket(api, scenario.ticket["id"])
        assert unchanged["execution_state"] == "DISPATCHED", (
            "a refused completion leaves the ticket waiting in DISPATCHED"
        )
        assert unchanged["completed_at"] is None
        ax.assert_timestamps_unchanged(before, unchanged, "ticket")
        assert fx.invoice_lines(api, scenario.contract_id) == []
