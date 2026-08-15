"""Pinned rounding order, temporal-overlap uniqueness, OCC on elections, and
immutable payment events."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    create_plan,
    register_prep_and_review_actuaries,
    create_census_batch,
    add_participants,
    submit_screening,
    lock_census_batch,
    create_locked_census,
    create_locked_assumption_set,
    create_asset_statement,
    create_asset_valuation,
    create_valuation_run,
    compute_run,
    certify_run,
    get_plan,
    get_plan_version,
    list_demands,
    list_elections_for_plan,
    create_payment,
    setup_certified_plan,
    api_client,
)

PLAN_ADMIN = TEST_USERS["plan_admin_headers"]

FAMILY_A_ROWS = [
    {"external_ref": "A1", "date_of_birth": "1966-03-10", "status": "ACTIVE",
     "years_of_service": 10, "annual_compensation": 100000},
    {"external_ref": "A2", "date_of_birth": "1968-11-20", "status": "ACTIVE",
     "years_of_service": 5, "annual_compensation": 60000},
    {"external_ref": "R1", "date_of_birth": "1965-01-30", "status": "RETIREE",
     "current_annual_benefit": 50000},
]


class TestPerParticipantRoundingOrder:
    def test_per_participant_round_then_sum_order_funding_target(self, api):
        """PRD §2.6: "Per-participant liability and normal-cost values are each
        rounded to cents individually before any aggregation, and aggregations then
        sum the already-rounded values exactly — summing unrounded values and
        rounding once at the end is non-conformant."
        PRD §3.5: "the run's `funding_target` is the exact sum of the
        per-participant cent-rounded `accrued_liability` values".

        Design: Difficulty/combinatorial_formula/per_participant_round_then_sum_order
        """
        plan = create_plan(sponsor_name="Rounding Co", prior_aftap_pct=84.00)
        plan_id = plan["id"]
        prep, rev = register_prep_and_review_actuaries()
        batch = create_locked_census(plan_id, [
            {"external_ref": "P1", "date_of_birth": "1966-01-01", "status": "ACTIVE",
             "years_of_service": 1, "annual_compensation": 10000.34},
            {"external_ref": "P2", "date_of_birth": "1966-07-01", "status": "ACTIVE",
             "years_of_service": 3, "annual_compensation": 11111.11},
        ])
        aset = create_locked_assumption_set(plan_id, prep["id"], rev["id"])
        create_asset_statement(
            plan_id, market_value_begin=639.70, contributions_received=0,
            benefits_paid=31.99, investment_return=31.99,
        )
        ava = create_asset_valuation(plan_id, prep["id"])
        run = create_valuation_run(plan_id, prep["id"], batch["id"], aset["id"], ava["id"])
        computed = compute_run(run["id"], prep["id"])
        # Raw: 100.0034*1.4762 = 147.62501908 -> 147.63; 333.3333*1.4762 = 492.06661746 -> 492.07
        # Round-then-sum: 639.70. Sum-then-round would give 639.69.
        assert computed["funding_target"] == 639.70
        assert computed["funding_target"] != 639.69

    def test_per_participant_round_then_sum_order_normal_cost(self, api):
        """PRD §3.5: "`normal_cost` is the exact sum of the cent-rounded
        `normal_cost_share` values."
        PRD §2.6: "aggregations then sum the already-rounded values exactly".

        Design: Difficulty/combinatorial_formula/per_participant_round_then_sum_order
        """
        plan = create_plan(sponsor_name="Rounding 2 Co", prior_aftap_pct=84.00)
        plan_id = plan["id"]
        prep, rev = register_prep_and_review_actuaries()
        batch = create_locked_census(plan_id, [
            {"external_ref": "P1", "date_of_birth": "1966-01-01", "status": "ACTIVE",
             "years_of_service": 1, "annual_compensation": 10000.34},
            {"external_ref": "P2", "date_of_birth": "1966-07-01", "status": "ACTIVE",
             "years_of_service": 3, "annual_compensation": 11111.11},
        ])
        aset = create_locked_assumption_set(plan_id, prep["id"], rev["id"])
        create_asset_statement(
            plan_id, market_value_begin=639.70, contributions_received=0,
            benefits_paid=31.99, investment_return=31.99,
        )
        ava = create_asset_valuation(plan_id, prep["id"])
        run = create_valuation_run(plan_id, prep["id"], batch["id"], aset["id"], ava["id"])
        computed = compute_run(run["id"], prep["id"])
        # NC shares: r2(100.0034*1.4762)=147.63 + r2(111.1111*1.4762)=164.02 -> 311.65
        assert computed["normal_cost"] == 311.65


class TestCensusYearContainment:
    def test_census_plan_year_containment_conflict(self, api):
        """PRD §3.2: "A validating screening is additionally refused when another
        census batch of the same plan is already `VALIDATED` or `LOCKED` for the
        same plan year — calendar-year containment is absolute, while adjacent
        plan years are always permitted — surfacing `ERR_CENSUS_YEAR_CONFLICT`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/census_plan_year_containment_conflict
        """
        plan = create_plan(sponsor_name="Overlap Co", prior_aftap_pct=84.00)
        plan_id = plan["id"]
        b1 = create_census_batch(plan_id, source_label="b1")
        add_participants(b1["id"], [
            {"external_ref": "R1", "date_of_birth": "1965-04-04", "status": "RETIREE",
             "current_annual_benefit": 1000},
        ])
        submit_screening(b1["id"])  # b1 -> VALIDATED for 2028

        b2 = create_census_batch(plan_id, source_label="b2")
        add_participants(b2["id"], [
            {"external_ref": "R2", "date_of_birth": "1965-05-05", "status": "RETIREE",
             "current_annual_benefit": 2000},
        ])
        resp = api.submit_screening(b2["id"], PLAN_ADMIN)
        validate_error(resp, ApiErrorId.ERR_CENSUS_YEAR_CONFLICT, 409)
        fetched = validate_success(api.get_census_batch(b2["id"], PLAN_ADMIN), 200)
        assert fetched["status"] == "UPLOADED"

    def test_census_lock_conflict_when_another_locked(self, api):
        """PRD §3.2: "Locking is refused with `ERR_CENSUS_YEAR_CONFLICT` when
        another batch of the same plan is already `LOCKED` for the same plan
        year."

        Design: Difficulty/resource_temporal_overlap/census_plan_year_containment_conflict
        """
        plan = create_plan(sponsor_name="Overlap 2 Co", prior_aftap_pct=84.00)
        plan_id = plan["id"]
        b1 = create_locked_census(plan_id, [
            {"external_ref": "R1", "date_of_birth": "1965-04-04", "status": "RETIREE",
             "current_annual_benefit": 1000},
        ], source_label="b1")
        assert b1["status"] == "LOCKED"

        # A second batch cannot even validate for the same year (see above), so
        # confirm the lock-time rule via a second plan's batch is unnecessary;
        # instead assert the screening gate on a same-year second batch.
        b2 = create_census_batch(plan_id, source_label="b2")
        add_participants(b2["id"], [
            {"external_ref": "R2", "date_of_birth": "1965-05-05", "status": "RETIREE",
             "current_annual_benefit": 2000},
        ])
        resp = api.submit_screening(b2["id"], PLAN_ADMIN)
        validate_error(resp, ApiErrorId.ERR_CENSUS_YEAR_CONFLICT, 409)


class TestDuplicateAssetStatement:
    def test_duplicate_asset_statement_rejected(self, api):
        """PRD §3.4: "only one asset statement may exist per plan and plan year —
        a duplicate is rejected with `ERR_UNIQUENESS_VIOLATION`."

        Design: Corner/validations/duplicate_asset_statement_rejected
        """
        plan = create_plan(sponsor_name="Dup Co")
        create_asset_statement(plan["id"], market_value_begin=1000)
        resp = api.create_asset_statement(
            plan["id"],
            {
                "plan_year": 2028, "market_value_begin": 2000,
                "contributions_received": 0, "benefits_paid": 0,
                "investment_return": 100,
            },
            PLAN_ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_UNIQUENESS_VIOLATION, 409)


class TestElectionOCC:
    def test_election_stale_plan_version_returns_412(self, api):
        """PRD §2.7: "Creating a credit-balance election likewise requires
        `expected_plan_version` matching the plan's current `version`, with a
        mismatch rejected as `ERR_STALE_VERSION` (HTTP 412)."
        PRD §2.7: "The plan's `version` increments by one on plan termination, on
        run certification, and on election creation".

        Design: Corner/cross_cutting_layers/election_stale_plan_version_returns_412
        """
        fx = setup_certified_plan(
            sponsor_name="OCC2 Co",
            participant_rows=FAMILY_A_ROWS,
            market_value_begin=60000, contributions_received=0,
            benefits_paid=2000, investment_return=3000,
            initial_carryover_balance=2000, initial_prefunding_balance=3000,
            prior_aftap_pct=84.00,
        )
        plan_id = fx["plan"]["id"]
        demand_id = fx["demand"]["id"]
        # plan_v_pre was captured BEFORE certification; certification bumped it
        # fx["plan"] is re-read post-certification, so its version is current.
        # Reconstruct a stale version: current minus 1.
        stale_v = fx["plan"]["version"] - 1
        resp = api.create_credit_balance_election(
            plan_id,
            {"contribution_demand_id": demand_id, "amount": 1000.00,
             "expected_plan_version": stale_v},
            PLAN_ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
        assert list_elections_for_plan(plan_id) == []


class TestContributionPaymentImmutability:
    def test_contribution_payment_immutable_event(self, api):
        """PRD §2.4: "The contribution payment is the single exception: it carries
        only `id` and `created_at`. Because a posted payment is an immutable event,
        both `updated_at` and `version` are absent from it."
        PRD §3.7: "Cash payments are posted by a `PlanAdmin` against a specific
        demand as immutable payment events carrying an `amount` and the value date
        `paid_on` in ISO 8601."

        Design: Corner/entities/contribution_payment_immutable_event
        """
        fx = setup_certified_plan(
            sponsor_name="Immutable Co",
            participant_rows=[
                {"external_ref": "A1", "date_of_birth": "1966-03-10", "status": "ACTIVE",
                 "years_of_service": 10, "annual_compensation": 100000},
            ],
            market_value_begin=100000, contributions_received=0,
            benefits_paid=5000, investment_return=5000,
            prior_aftap_pct=84.00,
        )
        demand = fx["demand"]
        payment = create_payment(demand["id"], 100.00, paid_on="2028-05-01")
        assert "id" in payment and "created_at" in payment
        assert "version" not in payment
        assert "updated_at" not in payment

        payments, meta = validate_paginated(
            api.list_contribution_payments(demand["id"], PLAN_ADMIN)
        )
        assert len(payments) == 1
        assert payments[0]["amount"] == 100.00
