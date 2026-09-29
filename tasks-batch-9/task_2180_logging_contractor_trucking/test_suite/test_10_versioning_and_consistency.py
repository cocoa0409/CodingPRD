"""Version pinning, compensating operations and the immediate consistency model."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_quota_position,
    build_network,
    cancel_load,
    compile_statement,
    create_haul_contractor,
    create_tract,
    deliver_load,
    dispatch_load,
    dispute_statement,
    file_all_coverages,
    line_amounts_by_type,
    list_production_plans,
    make_accountant_headers,
    read_haul_contractor,
    read_load,
    read_mill_contract,
    read_production_plan,
    read_settlement_statement,
    read_tract,
    read_truck,
    revise_statement,
    submit_statement,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTractVersionPinning:
    def test_a_stale_expected_tract_version_is_a_precondition_failure(
        self, api, ops_headers
    ):
        """PRD §2.6: "Compiling a production plan for a tract requires a non-optional
        `expected_tract_version` field in the request body, carrying the client's last
        observed `version` of that `Tract`. If it does not equal the tract's current
        `version`, the request is rejected with `ERR_STALE_TRACT_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_tract_version_on_plan_create_returns_precondition_failed
        """
        tract = create_tract()
        first = validate_success(
            api.create_production_plan(
                tract["id"],
                {
                    "target_tons_per_week": 600,
                    "plan_horizon_weeks": 8,
                    "expected_tract_version": tract["version"],
                },
                ops_headers,
            ),
            201,
        )

        response = api.create_production_plan(
            tract["id"],
            {
                "target_tons_per_week": 450,
                "plan_horizon_weeks": 10,
                "expected_tract_version": tract["version"],
            },
            ops_headers,
        )
        validate_error(response, ApiErrorId.ERR_STALE_TRACT_VERSION.value, 412)

        assert read_production_plan(tract["id"], first["id"])["status"] == "DRAFT"
        assert read_tract(tract["id"])["version"] == 2
        assert len(list_production_plans(tract["id"])) == 1

    def test_a_fresh_tract_version_lets_the_new_plan_supersede_the_prior_one(
        self, api, ops_headers
    ):
        """PRD §3.3: "A plan is created in `DRAFT` status; creating one supersedes the
        tract's history, so every prior plan on that tract whose status is `DRAFT` or
        `APPROVED` moves to `SUPERSEDED`, and the tract's `version` is incremented by
        1."
        PRD §2.6: "The reason is concrete: creating a plan supersedes any prior plan on
        the tract, so a writer working from a stale view of the tract would overwrite a
        supersede decision it never observed."

        Design: Corner/cross_cutting_complexity_layers/fresh_tract_version_lets_a_new_plan_supersede_the_prior_one
        """
        tract = create_tract()
        first = validate_success(
            api.create_production_plan(
                tract["id"],
                {
                    "target_tons_per_week": 600,
                    "plan_horizon_weeks": 8,
                    "expected_tract_version": tract["version"],
                },
                ops_headers,
            ),
            201,
        )
        refreshed = read_tract(tract["id"])
        assert refreshed["version"] == 2

        second = validate_success(
            api.create_production_plan(
                tract["id"],
                {
                    "target_tons_per_week": 450,
                    "plan_horizon_weeks": 10,
                    "expected_tract_version": refreshed["version"],
                },
                ops_headers,
            ),
            201,
        )

        assert read_production_plan(tract["id"], first["id"])["status"] == "SUPERSEDED"
        assert read_production_plan(tract["id"], second["id"])["status"] == "DRAFT"
        assert second["planned_volume_tons"] == pytest.approx(4500.00, abs=0.005)
        assert read_tract(tract["id"])["version"] == 3


class TestCarrierVersionPinning:
    def test_a_stale_expected_carrier_version_is_a_precondition_failure(self, api):
        """PRD §2.6: "Compiling a settlement statement requires a non-optional
        `expected_haul_contractor_version` field in the request body, carrying the
        client's last observed `version` of the `HaulContractor` being paid. If it does
        not equal the carrier's current `version`, the request is rejected with
        `ERR_STALE_HAUL_CONTRACTOR_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_haul_contractor_version_on_statement_compile_returns_precondition_failed
        """
        carrier = create_haul_contractor()
        file_all_coverages(carrier["id"])
        stale_version = read_haul_contractor(carrier["id"])["version"]

        first = compile_statement(
            {"hc_id": carrier["id"]},
            period_start="2026-08-01",
            period_end="2026-08-31",
            expected_haul_contractor_version=stale_version,
        )

        response = api.create_settlement_statement(
            {
                "haul_contractor_id": carrier["id"],
                "period_start": "2026-09-01",
                "period_end": "2026-09-30",
                "expected_haul_contractor_version": stale_version,
            },
            make_accountant_headers("acct-1"),
        )
        validate_error(
            response, ApiErrorId.ERR_STALE_HAUL_CONTRACTOR_VERSION.value, 412
        )

        assert read_settlement_statement(first["id"])["status"] == "DRAFT"
        rows, meta = validate_paginated(
            api.list_settlement_statements(
                make_accountant_headers("acct-1"),
                params={"haul_contractor_id": carrier["id"], "limit": 100},
            )
        )
        assert meta["total_count"] == 1

    def test_a_new_overlapping_statement_voids_the_prior_draft(self, api):
        """PRD §3.9: "An intersecting statement still in `DRAFT` is not a collision —
        it is instead **voided**: its lines are cleared, every money field resets to 0,
        and its `status` becomes the terminal `VOID`."
        PRD §3.9: "Compiling also increments the carrier's `version` by 1, and records
        the compiling accountant's `X-User-ID` as `compiled_by_user_id`."

        Design: Corner/cross_cutting_complexity_layers/a_new_overlapping_statement_voids_the_prior_draft
        """
        carrier = create_haul_contractor()
        file_all_coverages(carrier["id"])
        scn = {"hc_id": carrier["id"]}

        first = compile_statement(
            scn, period_start="2026-08-01", period_end="2026-08-31"
        )
        second = compile_statement(
            scn, period_start="2026-08-15", period_end="2026-09-15"
        )

        voided = read_settlement_statement(first["id"])
        assert voided["status"] == "VOID"
        assert voided["gross_pay_cents"] == 0
        assert len(voided["lines"]) == 0

        assert second["status"] == "DRAFT"
        assert second["period_start"] == "2026-08-15"


class TestConservedQuantities:
    def test_the_dispatch_debits_the_quota_and_the_cancel_returns_it_exactly(
        self, api, ops_headers
    ):
        """PRD §3.1: "`available_tons` is the committed quota less the reserved tonnage
        less the delivered tonnage, rounded half-up to two decimal places; it may
        legitimately go negative inside the overrun tolerance."
        PRD §3.7: "Cancellation moves the load to the terminal `CANCELLED`, causes its
        mill contract to lose the load's `estimated_net_tons` from `reserved_tons` and
        recompute `available_tons`, and returns a `FILLED` contract to `OPEN` when the
        freed tons push the available figure above zero."

        Design: Difficulty/compensating_invariant/quota_tons_are_conserved_across_dispatch_and_its_compensating_cancel
        """
        scn = build_network()

        before = read_mill_contract(scn["mc_a_id"])
        assert_quota_position(before)
        assert before["available_tons"] == pytest.approx(500.00, abs=0.005)

        load = dispatch_load(scn)
        during = read_mill_contract(scn["mc_a_id"])
        assert_quota_position(during)
        assert during["reserved_tons"] == pytest.approx(26.50, abs=0.005)
        assert during["available_tons"] == pytest.approx(473.50, abs=0.005)

        cancel_load(scn, load["id"], reason="landing shut down by wet ground")

        after = read_mill_contract(scn["mc_a_id"])
        assert_quota_position(after)
        assert after["available_tons"] == pytest.approx(500.00, abs=0.005)

    def test_the_compensated_quota_leaves_no_residue_on_the_contract_or_the_load(
        self, api, ops_headers
    ):
        """PRD §3.1: "Three tonnage figures are maintained on every contract and none
        of them is client-supplied."
        PRD §3.7: "A cancelled load's `settlement_status` stays `UNSETTLED` forever —
        cancelled wood never enters a settlement statement."

        Design: Difficulty/compensating_invariant/quota_tons_are_conserved_across_dispatch_and_its_compensating_cancel
        """
        scn = build_network()
        load = dispatch_load(scn)

        cancel_load(scn, load["id"], reason="landing shut down by wet ground")

        load_row = read_load(load["id"])
        assert load_row["dispatch_status"] == "CANCELLED"
        assert load_row["settlement_status"] == "UNSETTLED"

        contract = read_mill_contract(scn["mc_a_id"])
        assert contract["reserved_tons"] == pytest.approx(0.00, abs=0.005)
        assert contract["delivered_tons"] == pytest.approx(0.00, abs=0.005)
        assert contract["available_tons"] == pytest.approx(500.00, abs=0.005)
        assert contract["quota_tons"] == pytest.approx(500.00, abs=0.005)
        assert contract["status"] == "OPEN"

    def test_a_revise_recompiles_the_statement_to_the_same_cents(self, api):
        """PRD §3.9: "**Revising** moves a `DISPUTED` statement to `REVISED`, optionally
        recording a `note`. Every attached load returns `STATEMENTED → ACCRUED` on the
        settlement axis, with no money field on any load altered, and the statement's
        `lines`, `compliance_score_at_compile`, `holdback_pct`, `gross_pay_cents`,
        `reject_deduction_cents`, `holdback_cents`, `deduction_cents` and
        `net_pay_cents` are all recompiled from scratch over the same eligibility
        filter."

        Design: Difficulty/compensating_invariant/settlement_cents_are_conserved_across_submit_and_its_compensating_revise
        """
        scn = build_network()
        load, ticket = deliver_load(scn)
        statement = compile_statement(scn)
        gross_before = statement["gross_pay_cents"]
        assert gross_before == 34_828
        submit_statement(statement["id"], user_id="acct-1")

        dispute_statement(
            statement["id"],
            scn["carrier_headers"],
            dispute_reason="scaled grade challenged by the carrier",
        )
        revise_statement(statement["id"], note="recompiled with the same eligible load set")

        final = read_settlement_statement(statement["id"])
        assert final["status"] == "REVISED"
        assert final["gross_pay_cents"] == 34_828
        assert final["reject_deduction_cents"] == 0
        assert final["holdback_cents"] == 0
        assert final["deduction_cents"] == 0
        assert final["net_pay_cents"] == 34_828
        assert len(final["lines"]) == 3

    def test_the_revised_statement_returns_its_load_to_accrued_without_paying(
        self, api
    ):
        """PRD §3.9: "`gross_pay_cents` is the sum of the amounts over every `HAUL`,
        `FUEL_SURCHARGE` and `DEMURRAGE` line."
        PRD §3.9: "Every attached load returns `STATEMENTED → ACCRUED` on the
        settlement axis, with no money field on any load altered, and the statement's
        `lines`, `compliance_score_at_compile`, `holdback_pct`, `gross_pay_cents`,
        `reject_deduction_cents`, `holdback_cents`, `deduction_cents` and
        `net_pay_cents` are all recompiled from scratch over the same eligibility
        filter."
        PRD §3.2: "A carrier also accumulates `lifetime_settled_cents`, the running sum
        of `net_pay_cents` across every settlement statement of that carrier that has
        reached `PAID`."

        Design: Difficulty/compensating_invariant/settlement_cents_are_conserved_across_submit_and_its_compensating_revise
        """
        scn = build_network()
        load, ticket = deliver_load(scn)
        statement = compile_statement(scn)
        submit_statement(statement["id"], user_id="acct-1")

        dispute_statement(
            statement["id"],
            scn["carrier_headers"],
            dispute_reason="scaled grade challenged by the carrier",
        )
        revise_statement(statement["id"], note="recompiled with the same eligible load set")

        final = read_settlement_statement(statement["id"])
        earned = sum(
            line_amounts_by_type(final, "HAUL")
            + line_amounts_by_type(final, "FUEL_SURCHARGE")
            + line_amounts_by_type(final, "DEMURRAGE")
        )
        assert earned == 34_828

        load_row = read_load(load["id"])
        assert load_row["settlement_status"] == "ACCRUED"
        assert load_row["dispatch_status"] == "DELIVERED"
        assert read_haul_contractor(scn["hc_id"])["lifetime_settled_cents"] == 0


class TestImmediateConsistency:
    def test_the_quota_debit_is_visible_on_the_very_next_read(self, api, ops_headers):
        """PRD §3.6: "Dispatch also adds the estimated tonnage to the contract's
        `reserved_tons`, recomputes `available_tons`, increments the contract's
        `version` by 1, and may auto-transition the contract to `FILLED` as described
        above."
        PRD §3.1: "Its `status` is entirely derived and never set: a truck reads
        `OUT_OF_SERVICE` whenever its owning carrier's `compliance_status` is
        `SUSPENDED`; otherwise it reads `DISPATCHED` whenever at least one load on that
        truck has a `dispatch_status` of `DISPATCHED`, `IN_TRANSIT` or `AT_MILL`;
        otherwise it reads `AVAILABLE`."

        Design: Corner/consistency_model/dispatch_reflects_the_quota_debit_inside_the_same_request
        """
        scn = build_network()

        load = validate_success(
            api.create_load(
                {
                    "tract_id": scn["tract_id"],
                    "mill_contract_id": scn["mc_a_id"],
                    "haul_route_id": scn["route_a_id"],
                    "truck_id": scn["truck_id"],
                    "declared_species": "DOUGLAS_FIR",
                    "declared_grade": "SAWLOG_1",
                    "estimated_net_tons": 26.5,
                    "scheduled_depart_at": "2026-08-03T08:00:00Z",
                    "scheduled_arrive_at": "2026-08-03T10:00:00Z",
                },
                ops_headers,
            ),
            201,
        )
        assert load["provisional_haul_pay_cents"] == 32_590
        assert load["rate_cents_per_ton_mile"] == 22

        contract = validate_success(
            api.get_mill_contract(scn["mc_a_id"], ops_headers)
        )
        assert contract["reserved_tons"] == pytest.approx(26.50, abs=0.005)
        assert contract["available_tons"] == pytest.approx(473.50, abs=0.005)
        assert contract["status"] == "OPEN"
        assert read_truck(scn["hc_id"], scn["truck_id"])["status"] == "DISPATCHED"
