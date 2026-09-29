"""Two gates that live in another entity's data rather than in the addressed row.

A stage may only be activated while the store's licence period covers the whole of
that stage's window, and a final settlement may only be finalized once every
store's lease disposition has reached a terminal status.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    activate_markdown_stage,
    add_inventory_lot,
    add_markdown_stage,
    add_store,
    api_client,
    apply_for_license,
    approve_engagement,
    assert_instant_equals,
    assert_lease_disposition,
    assert_settlement,
    assert_surrender_waterfall_invariants,
    accept_settlement,
    checkpoint_markdown_stage,
    close_store,
    create_engagement,
    create_jurisdiction,
    decide_license,
    finalize_settlement,
    make_compliance_headers,
    make_consultant_headers,
    make_controller_headers,
    open_lease_disposition,
    open_settlement,
    pin_clock,
    post_sales_day,
    propose_settlement,
    read_engagement,
    read_store,
    record_landlord_response,
    send_lease_offer,
    submit_engagement,
    surrender_lease,
    validate_error,
    validate_success,
    wind_down_engagement,
)

APPAREL_LOT = {
    "category": "APPAREL", "source": "ORIGINAL", "units_initial": 1000,
    "unit_cost_cents": 2000, "unit_retail_cents": 5000,
}
ELECTRONICS_LOT = {
    "category": "ELECTRONICS", "source": "ORIGINAL", "units_initial": 200,
    "unit_cost_cents": 15000, "unit_retail_cents": 30000,
}
NY_RULES = {
    "code": "NY", "name": "New York", "gob_license_required": True,
    "max_sale_days": 60, "license_cooling_off_days": 30,
    "max_augmentation_ratio": 0.1, "augmentation_disclosure_required": True,
    "advertising_disclosure_required": False, "surrender_notice_days": 10,
}
FEE_BASED_LIQUIDATOR = {
    "economics_model": "FEE_BASED", "guaranty_pct": 0,
    "hybrid_retailer_excess_pct": 0, "expense_responsibility": "LIQUIDATOR",
    "shared_expense_liquidator_pct": 0, "sale_start_date": "2026-09-15",
    "target_end_date": "2026-11-30",
}
LICENSE_PERIOD = {
    "period_start_date": "2026-09-15", "period_end_date": "2026-10-14",
    "advertising_claim_codes": ["EVERYTHING_MUST_GO"],
}


def _read_stage(stage_id):
    return validate_success(
        api_client.get_markdown_stage(stage_id, make_consultant_headers())
    )


def _read_license(license_id):
    return validate_success(
        api_client.get_gob_license(license_id, make_compliance_headers())
    )


def _licensed_store(engagement_id, jurisdiction_id, store_code, address):
    store = add_store(
        engagement_id, jurisdiction_id, store_code=store_code, address_line=address,
    )
    add_inventory_lot(store["id"], **APPAREL_LOT)
    add_inventory_lot(store["id"], **ELECTRONICS_LOT)
    return store


def _store_with_one_covered_and_one_uncovered_stage_window():
    """One licence for 2026-09-15..2026-10-14 and a cadence that outruns it.

    Stage 2's window ends 2026-10-13, so its last selling day is 2026-10-12 and the
    licence covers it; stage 3's window ends 2026-10-20, so its last selling day is
    2026-10-19, which the same licence does not reach.
    """
    pin_clock("2026-09-15T00:00:00Z")
    jurisdiction = create_jurisdiction(**NY_RULES)
    engagement = create_engagement(**FEE_BASED_LIQUIDATOR)
    store = _licensed_store(
        engagement["id"], jurisdiction["id"], "S-401", "77 Harbor Rd",
    )
    submit_engagement(engagement["id"])
    approve_engagement(engagement["id"])
    license_row = apply_for_license(
        store["id"], license_number="NY-GOB-0401", **LICENSE_PERIOD
    )
    decide_license(license_row["id"])
    stage_one = add_markdown_stage(
        store["id"], stage_index=1, discount_pct=0.2, sell_through_target_pct=0.3,
        window_start_date="2026-09-15", window_end_date="2026-09-29",
    )
    stage_two = add_markdown_stage(
        store["id"], stage_index=2, discount_pct=0.4, sell_through_target_pct=0.6,
        window_start_date="2026-09-29", window_end_date="2026-10-13",
    )
    stage_three = add_markdown_stage(
        store["id"], stage_index=3, discount_pct=0.6, sell_through_target_pct=0.9,
        window_start_date="2026-10-13", window_end_date="2026-10-20",
    )
    activated_two = activate_markdown_stage(stage_two["id"])
    checkpoint_markdown_stage(stage_two["id"])
    refusal = api_client.activate_markdown_stage(
        stage_three["id"], make_consultant_headers()
    )
    return {
        "engagement": engagement,
        "store": store,
        "license": license_row,
        "stage_one": stage_one,
        "activated_two": activated_two,
        "stage_three": stage_three,
        "refusal": refusal,
    }


def _two_stores_at_the_exact_edge_of_their_licence_period():
    """Two identical licences and two stages differing by a single day.

    The first store's stage window ends 2026-10-15, so its last selling day is
    exactly the licence's `period_end_date`; the second's ends one day later and
    therefore needs a day the licence does not grant.
    """
    pin_clock("2026-09-15T00:00:00Z")
    jurisdiction = create_jurisdiction(**NY_RULES)
    engagement = create_engagement(**FEE_BASED_LIQUIDATOR)
    store_edge = _licensed_store(
        engagement["id"], jurisdiction["id"], "S-411", "1 Edge St",
    )
    store_over = _licensed_store(
        engagement["id"], jurisdiction["id"], "S-412", "2 Edge St",
    )
    submit_engagement(engagement["id"])
    approve_engagement(engagement["id"])
    for store, number in ((store_edge, "NY-GOB-0411"), (store_over, "NY-GOB-0412")):
        license_row = apply_for_license(
            store["id"], license_number=number, **LICENSE_PERIOD
        )
        decide_license(license_row["id"])
    stage_edge = add_markdown_stage(
        store_edge["id"], stage_index=1, discount_pct=0.2, sell_through_target_pct=0.3,
        window_start_date="2026-09-29", window_end_date="2026-10-15",
    )
    stage_over = add_markdown_stage(
        store_over["id"], stage_index=1, discount_pct=0.2, sell_through_target_pct=0.3,
        window_start_date="2026-09-29", window_end_date="2026-10-16",
    )
    return {
        "activated_edge": activate_markdown_stage(stage_edge["id"]),
        "stage_over": stage_over,
        "refusal_over": api_client.activate_markdown_stage(
            stage_over["id"], make_consultant_headers()
        ),
    }


class TestStageActivationNeedsLicenceCoverage:
    def test_a_window_the_licence_period_covers_activates(self):
        """The last selling day of the half-open window falls inside the period.

        The PRD says: "Putting a stage into force takes it `ARMED → ACTIVE` and
        stamps `activated_at` with the current logical-clock instant."

        Design: Difficulty/cross_entity_state_dependency/stage_activation_requires_license_period_to_cover_that_stage_window
        """
        scenario = _store_with_one_covered_and_one_uncovered_stage_window()
        activated = scenario["activated_two"]
        assert activated["stage_status"] == "ACTIVE"
        assert_instant_equals(
            activated["activated_at"], "2026-09-15T00:00:00Z", "activated_at"
        )

    def test_a_window_that_outruns_the_licence_period_is_refused(self):
        """The licence ends 2026-10-14 and the window's last selling day is
        2026-10-19.

        The PRD says: "Where the jurisdiction requires a licence, the store must hold
        an `APPROVED` licence whose period covers the stage's entire window — its
        `period_start_date` on or before the stage's `window_start_date`, and its
        `period_end_date` on or after the day immediately preceding the stage's
        `window_end_date`, which is the last day the half-open window actually sells
        — otherwise `ERR_LICENSE_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/stage_activation_requires_license_period_to_cover_that_stage_window
        """
        scenario = _store_with_one_covered_and_one_uncovered_stage_window()
        validate_error(
            scenario["refusal"], ApiErrorId.ERR_LICENSE_NOT_ACTIVE.value, 409
        )
        stage_three = _read_stage(scenario["stage_three"]["id"])
        assert stage_three["stage_status"] == "ARMED"
        assert stage_three["activated_at"] is None

    def test_neither_entity_s_own_state_explains_the_difference(self):
        """The same store and the same licence sit in the same statuses throughout.

        The PRD says: "In a jurisdiction whose `gob_license_required` flag is set, a
        store activated by the agreement approval sits in `LICENSE_PENDING` and sells
        nothing until a regulator grants it a going-out-of-business licence."

        Design: Difficulty/cross_entity_state_dependency/stage_activation_requires_license_period_to_cover_that_stage_window
        """
        scenario = _store_with_one_covered_and_one_uncovered_stage_window()
        assert _read_license(scenario["license"]["id"])["license_status"] == "APPROVED"
        assert read_store(scenario["store"]["id"])["store_status"] == "SELLING"

    def test_the_coverage_test_is_inclusive_of_the_licence_period_end_date(self):
        """A window whose last selling day equals the period end date activates.

        The PRD says: "`window_end_date`, which is the exclusive boundary after it,
        so a stage window is half-open and must end strictly later than it starts."

        Design: Difficulty/cross_entity_state_dependency/stage_activation_requires_license_period_to_cover_that_stage_window
        """
        scenario = _two_stores_at_the_exact_edge_of_their_licence_period()
        assert scenario["activated_edge"]["stage_status"] == "ACTIVE"
        validate_error(
            scenario["refusal_over"], ApiErrorId.ERR_LICENSE_NOT_ACTIVE.value, 409
        )
        stage_over = _read_stage(scenario["stage_over"]["id"])
        assert stage_over["stage_status"] == "ARMED"
        assert stage_over["activated_at"] is None


MILL_ROAD_LEASE = {
    "landlord_name": "Mill Road Trust", "surrender_deadline_date": "2026-12-01",
    "daily_holdover_rate_cents": 25000, "rent_arrears_cents": 400000,
    "cam_arrears_cents": 150000, "restoration_cost_cents": 600000,
    "fixture_reserve_price_cents": 900000, "surrender_credit_cents": 0,
}


def _read_settlement(settlement_id):
    return validate_success(
        api_client.get_settlement(settlement_id, make_controller_headers())
    )


def _read_disposition(disposition_id):
    return validate_success(
        api_client.get_lease_disposition(disposition_id, make_consultant_headers())
    )


def _accepted_final_settlement_behind_an_undisposed_lease():
    """Everything the finalize needs except a terminal lease disposition.

    The store is CLOSED, the engagement is in WIND_DOWN, the FINAL worksheet is
    ACCEPTED and no expense item exists at all — the only outstanding fact is that
    the lease negotiation stopped at AGREED.
    """
    pin_clock("2026-09-15T00:00:00Z")
    jurisdiction = create_jurisdiction(**NY_RULES)
    engagement = create_engagement(**FEE_BASED_LIQUIDATOR)
    store = _licensed_store(
        engagement["id"], jurisdiction["id"], "S-1101", "44 Mill Rd",
    )
    submit_engagement(engagement["id"])
    approve_engagement(engagement["id"])
    license_row = apply_for_license(
        store["id"], license_number="NY-GOB-1101", **LICENSE_PERIOD
    )
    decide_license(license_row["id"])
    disposition = open_lease_disposition(store["id"], **MILL_ROAD_LEASE)
    send_lease_offer(disposition["id"], 500000)
    agreed = record_landlord_response(disposition["id"], "ACCEPT")
    pin_clock("2026-09-20T00:00:00Z")
    post_sales_day(
        store["id"], business_date="2026-09-16",
        original_net_sales_cents=4200000, augmentation_net_sales_cents=0,
        original_units_sold=800, augmentation_units_sold=0,
    )
    pin_clock("2026-10-16T00:00:00Z")
    close_store(store["id"])
    wind_down_engagement(engagement["id"])
    settlement = accept_settlement(
        propose_settlement(open_settlement(engagement["id"], "FINAL")["id"])["id"]
    )
    refusal = api_client.finalize_settlement(
        settlement["id"], make_consultant_headers()
    )
    return {
        "engagement": engagement,
        "store": store,
        "disposition": agreed,
        "settlement": settlement,
        "refusal": refusal,
    }


class TestFinalizeNeedsEveryLeaseDisposed:
    def test_an_agreed_lease_blocks_the_finalize(self):
        """AGREED is not one of the two dispositions that satisfy the gate.

        The PRD says: "And every store must have a lease disposition that has reached
        `SURRENDERED` or `REJECTED_FINAL`, with no expense item of the engagement left
        `SUBMITTED`, otherwise `ERR_LEASE_NOT_DISPOSED` — a store with no lease
        disposition at all fails this test just as surely as one still
        mid-negotiation, and a single un-decided expense item blocks the close because
        the settlement was computed without it."

        Design: Difficulty/cross_entity_state_dependency/final_settlement_finalize_requires_every_lease_disposition_terminal
        """
        scenario = _accepted_final_settlement_behind_an_undisposed_lease()
        validate_error(
            scenario["refusal"], ApiErrorId.ERR_LEASE_NOT_DISPOSED.value, 409
        )
        assert scenario["disposition"]["disposition_status"] == "AGREED"

    def test_every_other_precondition_of_the_finalize_already_held(self):
        """Right status, right basis, store closed, engagement winding down.

        The PRD says: "Finalizing is the last act of the engagement, performed by the
        `LiquidationConsultant`, and it is defined only from `ACCEPTED`; any other
        status draws `ERR_SETTLEMENT_STATE_INVALID`."

        Design: Difficulty/cross_entity_state_dependency/final_settlement_finalize_requires_every_lease_disposition_terminal
        """
        scenario = _accepted_final_settlement_behind_an_undisposed_lease()
        settlement = _read_settlement(scenario["settlement"]["id"])
        assert_settlement(settlement)
        assert settlement["settlement_status"] == "ACCEPTED"
        assert settlement["settlement_basis"] == "FINAL"
        assert read_store(scenario["store"]["id"])["store_status"] == "CLOSED"
        engagement = read_engagement(scenario["engagement"]["id"])
        assert engagement["engagement_status"] == "WIND_DOWN"
        assert settlement["recovery_ratio"] == pytest.approx(0.8400, abs=0.00001)
        assert settlement["fee_rate"] == pytest.approx(0.0500, abs=0.00001)
        assert settlement["liquidator_fee_cents"] == 210000
        assert settlement["retailer_proceeds_cents"] == 3990000
        assert settlement["liquidator_proceeds_cents"] == 210000
        assert settlement["expense_total_cents"] == 0

    def test_the_surrender_pours_the_fixture_money_through_the_waterfall(self):
        """1,000,000 of fixture proceeds against 1,150,000 of claims, in bucket order.

        The PRD says: "Those funds are poured into exactly four buckets in a fixed
        order that must not be reordered: first the rent arrears, second the CAM
        arrears, third the restoration cost, and fourth the holdover penalty."

        Design: Difficulty/cross_entity_state_dependency/final_settlement_finalize_requires_every_lease_disposition_terminal
        """
        scenario = _accepted_final_settlement_behind_an_undisposed_lease()
        surrendered = surrender_lease(scenario["disposition"]["id"], 1000000)
        assert_lease_disposition(surrendered)
        assert surrendered["holdover_days"] == 0
        assert surrendered["holdover_penalty_cents"] == 0
        assert surrendered["allocated_rent_cents"] == 400000
        assert surrendered["allocated_cam_cents"] == 150000
        assert surrendered["allocated_restoration_cents"] == 450000
        assert surrendered["allocated_holdover_cents"] == 0
        assert surrendered["unpaid_landlord_balance_cents"] == 150000
        assert surrendered["residual_to_retailer_cents"] == 0
        assert_surrender_waterfall_invariants(surrendered)
        assert surrendered["disposition_status"] == "SURRENDERED"
        assert read_store(scenario["store"]["id"])["store_status"] == "SURRENDERED"

    def test_the_identical_finalize_succeeds_once_the_lease_is_surrendered(self):
        """The gate was the only thing standing between ACCEPTED and FINALIZED.

        The PRD says: "Finalization takes the worksheet `ACCEPTED → FINALIZED`, moves
        every `APPROVED` expense item of the engagement to `SETTLED` without
        disturbing the engagement's expense aggregates, takes the engagement
        `WIND_DOWN → CLOSED`, and increments both the worksheet's and the
        engagement's `version` by 1."

        Design: Difficulty/cross_entity_state_dependency/final_settlement_finalize_requires_every_lease_disposition_terminal
        """
        scenario = _accepted_final_settlement_behind_an_undisposed_lease()
        surrender_lease(scenario["disposition"]["id"], 1000000)
        finalized = finalize_settlement(scenario["settlement"]["id"])
        assert finalized["settlement_status"] == "FINALIZED"
        assert _read_disposition(scenario["disposition"]["id"])[
            "disposition_status"
        ] == "SURRENDERED"
        engagement = read_engagement(scenario["engagement"]["id"])
        assert engagement["engagement_status"] == "CLOSED"
