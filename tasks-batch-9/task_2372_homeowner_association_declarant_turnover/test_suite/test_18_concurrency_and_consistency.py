"""The association version as an OCC token and a write counter, and immediate reads."""

from typing import Any, Dict

import pytest
from test_helpers import (
    CLAIM_ACTION_RESERVE,
    CLAIM_ACTION_WITHDRAW,
    ERR_STALE_ASSOCIATION_VERSION,
    FUNDING_METHOD_CASH_FLOW,
    RECORDS_ACTION_ACCEPT,
    VALUATION_BASIS_REPAIR_COST,
    ApiClient,
    assert_claim_pool_conserved,
    assert_claim_reserve_breakdown,
    assert_pct,
    assert_schedule_waterfall,
    assessment_schedule_payload,
    build_adopted_reserve_study,
    build_conveyed_component,
    claim_action_payload,
    create_schedule_with_fresh_version,
    do_advance_financial,
    do_claim_notice,
    do_close_sale,
    do_deliver_item,
    fresh_association_version,
    make_transition_committee_headers,
    read_association,
    read_turnover_case,
    records_transition_payload,
    seed_association,
    seed_audit_engagement,
    seed_defect_claim,
    seed_lot,
    seed_records_item,
    seed_turnover_case,
    validate_error,
    validate_paginated,
    validate_success,
)

FISCAL_YEAR = 2027
OPERATING_COST_CENTS = 4000000


# ─── Wetherlam: the one optimistic-concurrency rule in the system ──────


@pytest.fixture
def wetherlam(api: ApiClient) -> Dict[str, Any]:
    """Three of four lots closed, an adopted study, and the subsidy already ended."""
    association = seed_association(
        api,
        name="Wetherlam",
        total_planned_lots=4,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2027-01-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=1200000,
        reserve_claim_pool_cents=0,
        declarant_monthly_subsidy_cents=150000,
    )
    case = seed_turnover_case(api, association["id"], total_seats=3)
    lots = [seed_lot(api, association["id"], f"W-{index}") for index in range(1, 5)]
    for lot, closing_date in zip(
        lots[:3],
        ("2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z", "2026-04-01T00:00:00Z"),
    ):
        do_close_sale(api, lot["id"], closing_date)
    build_adopted_reserve_study(
        api,
        association["id"],
        funding_method=FUNDING_METHOD_CASH_FLOW,
        planned_annual_contribution_cents=700000,
        projected_annual_expenditure_cents=500000,
    )
    seed_audit_engagement(
        api, association["id"], "2026-01-01T00:00:00Z", "2026-06-30T00:00:00Z"
    )
    do_advance_financial(api, case["id"], association["id"], "2026-10-01T00:00:00Z")
    return {
        "association": association,
        "case": case,
        "lots": lots,
        "committee_headers": make_transition_committee_headers(association["id"]),
    }


def _create_schedule_with_version(
    api: ApiClient, association_id: str, version: int
) -> Any:
    """POST the FY2027 schedule carrying a version the caller chose."""
    return api.create_assessment_schedule(
        assessment_schedule_payload(
            association_id,
            version,
            fiscal_year=FISCAL_YEAR,
            projected_operating_cost_cents=OPERATING_COST_CENTS,
        ),
        make_transition_committee_headers(association_id),
    )


class TestStaleAssociationVersion:
    """A version read before the fourth closing no longer describes the community."""

    def test_the_stale_version_is_refused_and_creates_nothing(
        self, api: ApiClient, wetherlam: Dict[str, Any]
    ) -> None:
        """The intervening closing moved the association out from under the client.

        "The creation payload must carry `expected_association_version` — a
        required field, not an optional one — holding the `version` the client
        last observed on the `Association`. If that value does not equal the
        association's current `version`, the request is rejected with
        `ERR_STALE_ASSOCIATION_VERSION` and HTTP 412, and nothing is created."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_association_version_is_rejected_then_the_fresh_read_succeeds
        """
        association_id = wetherlam["association"]["id"]
        stale_version = fresh_association_version(api, association_id)

        do_close_sale(api, wetherlam["lots"][3]["id"], "2026-07-15T00:00:00Z")
        moved = read_association(api, association_id)
        assert moved["sold_lot_count"] == 4
        assert_pct(moved["sold_lot_pct"], 100.00, "sold_lot_pct")

        validate_error(
            _create_schedule_with_version(api, association_id, stale_version),
            ERR_STALE_ASSOCIATION_VERSION,
        )

        _rows, meta = validate_paginated(
            api.list_assessment_schedules(
                association_id, wetherlam["committee_headers"]
            )
        )
        assert meta["total_count"] == 0, "A 412 leaves no schedule behind"

    def test_the_fresh_read_succeeds_on_the_four_lot_divisor(
        self, api: ApiClient, wetherlam: Dict[str, Any]
    ) -> None:
        """Four billable lots put the per-lot figure at 97,917, not at 130,556.

        "`per_lot_monthly_assessment_cents` is `annual_requirement_cents` divided
        by `billable_lot_count` times twelve months, rounded **up** to the next
        whole cent."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_association_version_is_rejected_then_the_fresh_read_succeeds
        """
        association_id = wetherlam["association"]["id"]
        stale_version = fresh_association_version(api, association_id)

        do_close_sale(api, wetherlam["lots"][3]["id"], "2026-07-15T00:00:00Z")
        validate_error(
            _create_schedule_with_version(api, association_id, stale_version),
            ERR_STALE_ASSOCIATION_VERSION,
        )

        retry_version = fresh_association_version(api, association_id)
        assert retry_version != stale_version, (
            "The closing advanced the version the client had captured"
        )

        schedule = validate_success(
            create_schedule_with_fresh_version(
                api, association_id, FISCAL_YEAR, OPERATING_COST_CENTS
            ),
            expected_status=201,
        )
        assert_schedule_waterfall(
            schedule,
            billable_lot_count=4,
            reserve_contribution=700000,
            subsidy_offset=0,
            annual_requirement=4700000,
            per_lot_monthly=97917,
            annual_total=4700016,
            residual=16,
        )
        assert schedule["per_lot_monthly_assessment_cents"] != 130556, (
            "Honouring the stale three-lot view would have billed 130,556 per lot"
        )


# ─── Yealmpton: the version is a write counter ─────────────────────────


@pytest.fixture
def yealmpton(api: ApiClient) -> Dict[str, Any]:
    """A noticed claim standing against a 3,000,000 cent claim pool."""
    association = seed_association(
        api,
        name="Yealmpton",
        total_planned_lots=4,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2027-01-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=0,
        reserve_claim_pool_cents=3000000,
        declarant_monthly_subsidy_cents=0,
    )
    component = build_conveyed_component(
        api,
        association["id"],
        effective_date="2024-01-01T00:00:00Z",
        name="Podium Deck",
        category="STRUCTURE",
        replacement_cost_cents=2000000,
        useful_life_years=30,
        effective_age_years=2,
        promised_completion_date="2024-01-01T00:00:00Z",
    )
    claim = seed_defect_claim(
        api,
        association["id"],
        component["id"],
        defect_summary="Deck waterproofing failure",
        repair_cost_estimate_cents=1500000,
        diminution_value_cents=900000,
    )
    do_claim_notice(api, claim["id"], association["id"])
    return {
        "association": association,
        "claim": claim,
        "committee_headers": make_transition_committee_headers(association["id"]),
    }


class TestVersionAdvancesOncePerWrite:
    """Each pool-moving write advances the version by exactly one."""

    def test_the_reserve_advances_the_version_by_one(
        self, api: ApiClient, yealmpton: Dict[str, Any]
    ) -> None:
        """One call, one increment, and the committed pool moved with it.

        "`version` is an integer that starts at 1 on creation and increments by
        one on every mutation."

        Design: Corner/cross_cutting_complexity_layers/association_version_advances_once_per_write_that_moves_a_derived_field
        """
        association_id = yealmpton["association"]["id"]
        before_version = fresh_association_version(api, association_id)

        reserved = validate_success(
            api.defect_claim_action(
                yealmpton["claim"]["id"],
                claim_action_payload(
                    CLAIM_ACTION_RESERVE, valuation_basis=VALUATION_BASIS_REPAIR_COST
                ),
                yealmpton["committee_headers"],
            )
        )
        assert reserved["status"] == "RESERVED"
        assert reserved["reserved_amount_cents"] == 1680000

        after = read_association(api, association_id)
        assert after["reserve_claim_committed_cents"] == 1680000
        assert after["reserve_claim_available_cents"] == 1320000
        assert after["version"] == before_version + 1, (
            "One write must not advance the version twice"
        )

    def test_the_compensating_withdrawal_advances_it_again_and_never_backwards(
        self, api: ApiClient, yealmpton: Dict[str, Any]
    ) -> None:
        """The pool returns to 3,000,000 while the version keeps climbing.

        "Recomputation of a derived field counts as a mutation. When the close of
        a lot sale moves an association's `sold_lot_count`, when a claim reserve
        moves its `reserve_claim_committed_cents`, or when a cascade flips its
        `budget_forecast_status`, the association's `updated_at` is refreshed and
        its `version` advances"

        Design: Corner/cross_cutting_complexity_layers/association_version_advances_once_per_write_that_moves_a_derived_field
        """
        association_id = yealmpton["association"]["id"]
        committee = yealmpton["committee_headers"]
        claim_id = yealmpton["claim"]["id"]

        opening_version = fresh_association_version(api, association_id)
        validate_success(
            api.defect_claim_action(
                claim_id,
                claim_action_payload(
                    CLAIM_ACTION_RESERVE, valuation_basis=VALUATION_BASIS_REPAIR_COST
                ),
                committee,
            )
        )
        reserved_version = fresh_association_version(api, association_id)

        withdrawn = validate_success(
            api.defect_claim_action(
                claim_id, claim_action_payload(CLAIM_ACTION_WITHDRAW), committee
            )
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["reserved_amount_cents"] == 0

        released = read_association(api, association_id)
        assert released["reserve_claim_committed_cents"] == 0
        assert released["reserve_claim_available_cents"] == 3000000
        assert released["version"] == reserved_version + 1
        assert released["version"] > opening_version, (
            "The version is a write counter, not a hash of the balances"
        )


# ─── Zeals Barrow: no read-after-write lag anywhere ────────────────────


@pytest.fixture
def zeals_barrow(api: ApiClient) -> Dict[str, Any]:
    """A noticed claim and two required records items, the first already delivered."""
    association = seed_association(
        api,
        name="Zeals Barrow",
        total_planned_lots=4,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2027-01-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=0,
        reserve_claim_pool_cents=3000000,
        declarant_monthly_subsidy_cents=0,
    )
    case = seed_turnover_case(api, association["id"], total_seats=3)
    component = build_conveyed_component(
        api,
        association["id"],
        effective_date="2024-01-01T00:00:00Z",
        name="Terrace Slab",
        category="STRUCTURE",
        replacement_cost_cents=2000000,
        useful_life_years=30,
        effective_age_years=2,
        promised_completion_date="2024-01-01T00:00:00Z",
    )
    claim = seed_defect_claim(
        api,
        association["id"],
        component["id"],
        defect_summary="Terrace slab cracking",
        repair_cost_estimate_cents=1500000,
        diminution_value_cents=900000,
    )
    do_claim_notice(api, claim["id"], association["id"])
    first_item = seed_records_item(api, case["id"], "FINANCIAL_RECORDS", required=True)
    second_item = seed_records_item(api, case["id"], "PERMITS", required=True)
    do_deliver_item(api, first_item["id"])
    return {
        "association": association,
        "case": case,
        "claim": claim,
        "first_item": first_item,
        "second_item": second_item,
        "committee_headers": make_transition_committee_headers(association["id"]),
    }


class TestDerivedFieldsAreImmediate:
    """The transition's own response is already correct, and so is the next read."""

    def test_the_reserve_response_and_the_next_association_read_are_both_current(
        self, api: ApiClient, zeals_barrow: Dict[str, Any]
    ) -> None:
        """No second call is needed to see the fee, the total or the pools.

        "Unless otherwise noted, operations that create or modify a resource will
        return the created or updated resource object in the data field."

        Design: Corner/consistency_model/derived_fields_are_current_in_the_same_response_that_moves_them
        """
        association_id = zeals_barrow["association"]["id"]

        reserved = validate_success(
            api.defect_claim_action(
                zeals_barrow["claim"]["id"],
                claim_action_payload(
                    CLAIM_ACTION_RESERVE, valuation_basis=VALUATION_BASIS_REPAIR_COST
                ),
                zeals_barrow["committee_headers"],
            )
        )
        assert_claim_reserve_breakdown(
            reserved, subtotal=1500000, fee=180000, reserved=1680000
        )

        association = read_association(api, association_id)
        assert association["reserve_claim_committed_cents"] == 1680000
        assert association["reserve_claim_available_cents"] == 1320000
        assert_claim_pool_conserved(association)

    def test_the_case_read_after_an_acceptance_already_carries_the_new_percentage(
        self, api: ApiClient, zeals_barrow: Dict[str, Any]
    ) -> None:
        """One of two required items accepted reads as exactly 50.00.

        "The figure is recomputed whenever an item is registered, accepted or
        rejected, and it gates the transition twice: the governance handover of
        §3.4 needs at least 80.00, and final settlement needs exactly 100.00."

        Design: Corner/consistency_model/derived_fields_are_current_in_the_same_response_that_moves_them
        """
        case_id = zeals_barrow["case"]["id"]
        committee = zeals_barrow["committee_headers"]

        accepted = validate_success(
            api.records_item_transition(
                zeals_barrow["first_item"]["id"],
                records_transition_payload(RECORDS_ACTION_ACCEPT),
                committee,
            )
        )
        assert accepted["status"] == "ACCEPTED"

        case = read_turnover_case(api, case_id)
        assert_pct(
            case["records_transfer_completeness_pct"],
            50.00,
            "records_transfer_completeness_pct",
        )

        rows, _meta = validate_paginated(api.list_records_items(case_id, committee))
        outstanding = next(
            row for row in rows if row["id"] == zeals_barrow["second_item"]["id"]
        )
        assert outstanding["status"] == "OUTSTANDING"
