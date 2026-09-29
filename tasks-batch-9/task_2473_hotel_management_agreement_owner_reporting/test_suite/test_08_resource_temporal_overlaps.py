"""Slot collisions with no extent, and half-open windows that may legitimately touch."""

from test_helpers import (
    ASSET_HEADERS,
    ApiErrorId,
    BudgetDecision,
    DisputeStatus,
    MANAGER_HEADERS,
    assert_error_envelope,
    assert_object_envelope,
    assert_page,
    brand_dispute_payload,
    package_payload,
)


# ---------------------------------------------------------------------------
# The discrete month slot: only an exact repeat collides
# ---------------------------------------------------------------------------


def _period_slot_hotel(scenario):
    """An agreement whose (2026, 9) month slot is already occupied."""
    agreement = scenario.register(
        hotel_name="Period Slot Hotel",
        owner_entity_name="Slot Owner LLC",
        base_fee_pct=0.0325,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
    )
    scenario.activate(agreement["id"])
    budget = scenario.budget(
        agreement["id"],
        fiscal_year=2026,
        budgeted_revenue_cents=600000000,
        budgeted_operating_expenses_cents=400000000,
    )
    scenario.submit_budget(budget["id"])
    scenario.decide_budget(budget["id"], BudgetDecision.APPROVE)

    september = scenario.expert_package(agreement["id"], fiscal_year=2026, period_month=9)
    return {"agreement_id": agreement["id"], "september_id": september["id"]}


def _open_period(scenario, agreement_id, fiscal_year, period_month, **overrides):
    return scenario.api.create_report_package(
        agreement_id,
        package_payload(fiscal_year=fiscal_year, period_month=period_month, **overrides),
        MANAGER_HEADERS,
    )


class TestReportPeriodSlotUniqueness:
    def test_an_exact_repeat_of_the_month_slot_is_refused(self, scenario):
        """PRD §2.8 rule 36: "No other report package of the agreement already occupies the
        month slot formed by `fiscal_year` and `period_month`; adjacent months never collide.
        Otherwise `ERR_PERIOD_ALREADY_REPORTED` (409)."

        Design: Difficulty/resource_temporal_overlap/report_period_slot_uniqueness_rejects_only_the_same_month
        """
        state = _period_slot_hotel(scenario)

        response = _open_period(
            scenario,
            state["agreement_id"],
            2026,
            9,
            rooms_revenue_cents=1000000,
            fnb_revenue_cents=0,
            other_revenue_cents=0,
            operating_expenses_cents=0,
        )

        assert_error_envelope(response, ApiErrorId.PERIOD_ALREADY_REPORTED)
        assert response.status_code == 409

        # The sitting tenant of the slot kept every one of its own inputs.
        september = scenario.read_package(state["september_id"])
        assert september["rooms_revenue_cents"] == 40000015
        assert september["fnb_revenue_cents"] == 12000005
        assert september["other_revenue_cents"] == 3000005
        assert september["due_date_utc"].startswith("2026-10-25T00:00:00")

    def test_the_adjacent_and_year_rolling_months_are_accepted(self, scenario):
        """PRD §3.4: "The `due_date_utc` — the reporting deadline — is the twenty-fifth day of
        the month following the reported period at midnight UTC; for a period whose
        `period_month` is 12, it rolls to the twenty-fifth of January in the following
        calendar year."

        Design: Difficulty/resource_temporal_overlap/report_period_slot_uniqueness_rejects_only_the_same_month
        """
        state = _period_slot_hotel(scenario)

        october = assert_object_envelope(
            _open_period(
                scenario,
                state["agreement_id"],
                2026,
                10,
                rooms_revenue_cents=21000000,
                fnb_revenue_cents=5000000,
                other_revenue_cents=1000000,
                operating_expenses_cents=6000000,
            ),
            201,
        )
        december = assert_object_envelope(
            _open_period(
                scenario,
                state["agreement_id"],
                2026,
                12,
                rooms_revenue_cents=22000000,
                fnb_revenue_cents=5000000,
                other_revenue_cents=1000000,
                operating_expenses_cents=6000000,
            ),
            201,
        )

        assert october["due_date_utc"].startswith("2026-11-25T00:00:00")
        assert december["due_date_utc"].startswith("2027-01-25T00:00:00")

    def test_the_same_month_of_the_next_fiscal_year_is_accepted(self, scenario):
        """PRD §3.4: "Two figures are derived the moment the period is opened, from that
        package's own inputs and no sibling's."

        Design: Difficulty/resource_temporal_overlap/report_period_slot_uniqueness_rejects_only_the_same_month
        """
        state = _period_slot_hotel(scenario)
        _open_period(scenario, state["agreement_id"], 2026, 10)
        _open_period(scenario, state["agreement_id"], 2026, 12)

        next_year = assert_object_envelope(
            _open_period(
                scenario,
                state["agreement_id"],
                2027,
                9,
                rooms_revenue_cents=23000000,
                fnb_revenue_cents=5000000,
                other_revenue_cents=1000000,
                operating_expenses_cents=6000000,
            ),
            201,
        )

        assert next_year["due_date_utc"].startswith("2027-10-25T00:00:00")
        assert_page(
            scenario.api.list_report_packages(state["agreement_id"], MANAGER_HEADERS),
            expected_rows=4,
            total_count=4,
            has_more=False,
        )


# ---------------------------------------------------------------------------
# The half-open standstill window: touching endpoints do not overlap
# ---------------------------------------------------------------------------


def _standstill_window_hotel(scenario):
    """One dispute escalated at the epoch, so its standstill runs to 2026-09-15."""
    agreement = scenario.register(
        hotel_name="Standstill Window Hotel",
        owner_entity_name="Half Open Owner LLC",
        base_fee_pct=0.0325,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
        dispute_standstill_days=45,
        max_dispute_rounds=1,
    )
    scenario.activate(agreement["id"])

    dispute = scenario.dispute(
        agreement["id"],
        franchise_requirement_ref="BSR-2026-014",
        estimated_cost_cents=1500000,
        remediation_start_utc="2026-06-01T00:00:00Z",
        remediation_deadline_utc="2026-08-15T00:00:00Z",
    )
    scenario.manager_response(dispute["id"], 1500000)
    scenario.owner_counter(dispute["id"], 1400000)
    scenario.escalate(dispute["id"])
    return {"agreement_id": agreement["id"], "escalated_id": dispute["id"]}


def _open_dispute(scenario, agreement_id, ref, start):
    return scenario.api.create_brand_dispute(
        agreement_id,
        brand_dispute_payload(
            franchise_requirement_ref=ref,
            estimated_cost_cents=900000,
            remediation_start_utc=start,
            remediation_deadline_utc="2026-10-15T00:00:00Z",
        ),
        ASSET_HEADERS,
    )


class TestDisputeStandstillHalfOpenWindow:
    def test_escalation_pins_the_standstill_window(self, scenario):
        """PRD §3.9: "Escalation sets `standstill_start_utc` to the current logical clock and
        `standstill_end_utc` to that instant advanced by the agreement's
        `dispute_standstill_days`."

        Design: Difficulty/resource_temporal_overlap/dispute_standstill_half_open_window_touching_boundary_allowed
        """
        state = _standstill_window_hotel(scenario)

        escalated = next(
            row
            for row in scenario.disputes(state["agreement_id"])
            if row["id"] == state["escalated_id"]
        )

        assert escalated["status"] == DisputeStatus.ESCALATED_TO_FRANCHISOR
        assert escalated["standstill_start_utc"].startswith("2026-08-01T00:00:00")
        assert escalated["standstill_end_utc"].startswith("2026-09-15T00:00:00")

    def test_a_window_beginning_where_the_standstill_ends_is_admissible(self, scenario):
        """PRD §3.9: "Because both windows are half-open, windows that merely touch at an
        endpoint — one ending exactly where the other begins — do not overlap and are
        admissible; only a genuine interior overlap is refused, and a different
        `franchise_requirement_ref` never conflicts." and "The dispute opens in `OPENED` with
        `round` at 0, `current_cost_estimate_cents` seeded from `estimated_cost_cents`,
        `funding_source` null and `funded_amount_cents` at zero."

        Design: Difficulty/resource_temporal_overlap/dispute_standstill_half_open_window_touching_boundary_allowed
        """
        state = _standstill_window_hotel(scenario)

        touching = assert_object_envelope(
            _open_dispute(
                scenario, state["agreement_id"], "BSR-2026-014", "2026-09-15T00:00:00Z"
            ),
            201,
        )

        assert touching["status"] == DisputeStatus.OPENED
        assert touching["round"] == 0
        assert touching["current_cost_estimate_cents"] == 900000
        assert touching["funded_amount_cents"] == 0
        assert touching["funding_source"] is None

    def test_one_day_of_interior_overlap_is_refused_unless_the_reference_differs(self, scenario):
        """PRD §2.8 rule 35: "The new dispute's remediation window, taken as half-open from
        `remediation_start_utc` inclusive to `remediation_deadline_utc` exclusive, does not
        overlap the half-open standstill window from `standstill_start_utc` inclusive to
        `standstill_end_utc` exclusive of any existing dispute on the same agreement and the
        same `franchise_requirement_ref` whose `status` is `ESCALATED_TO_FRANCHISOR`; windows
        that merely touch at an endpoint do not overlap. Otherwise
        `ERR_DISPUTE_WINDOW_CONFLICT` (409)."

        Design: Difficulty/resource_temporal_overlap/dispute_standstill_half_open_window_touching_boundary_allowed
        """
        state = _standstill_window_hotel(scenario)
        _open_dispute(scenario, state["agreement_id"], "BSR-2026-014", "2026-09-15T00:00:00Z")

        overlapping = _open_dispute(
            scenario, state["agreement_id"], "BSR-2026-014", "2026-09-14T00:00:00Z"
        )
        assert_error_envelope(overlapping, ApiErrorId.DISPUTE_WINDOW_CONFLICT)
        assert overlapping.status_code == 409

        other_reference = assert_object_envelope(
            _open_dispute(
                scenario, state["agreement_id"], "BSR-2026-099", "2026-09-14T00:00:00Z"
            ),
            201,
        )
        assert other_reference["status"] == DisputeStatus.OPENED
        assert_page(
            scenario.api.list_brand_disputes(state["agreement_id"], MANAGER_HEADERS),
            expected_rows=3,
            total_count=3,
            has_more=False,
        )
