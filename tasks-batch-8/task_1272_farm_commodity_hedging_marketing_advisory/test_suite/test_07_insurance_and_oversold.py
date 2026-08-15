"""Crop insurance: guarantee floor at bind, indemnity at claim, and the
over-sold tripwire interaction with sales contracts."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_grower_headers,
    create_operation,
    create_certified_baseline,
    create_policy_payload,
    setup_active_plan_with_buyer,
    create_flat_contract,
    create_contract_payload,
)

ADVISOR = TEST_USERS["advisor_headers"]


class TestInsuranceGuarantee:
    def test_insurance_guarantee_floor_and_indemnity(self, api):
        """PRD §3.2: "At bind time the policy's `guarantee_bushels` is computed
        once and frozen as the floor of the referenced baseline's operative
        `expected_bushels` multiplied by `coverage_level_pct`; later baseline
        supersedes do not retroactively change the frozen guarantee." and "The
        `indemnity_dollars` are computed and frozen as the shortfall — the
        greater of zero and the guarantee minus the actual harvest —
        multiplied by the greater of `projected_price` and `harvest_price`,
        rounded to two decimal places half-up."

        Design: Corner/calculations/insurance_guarantee_floor_and_indemnity
        """
        op = create_operation(
            name="Ins Farm", primary_commodity="CORN", crop_year=2026,
            risk_profile="BALANCED", yield_method="APH",
        )
        baseline = create_certified_baseline(op, planted_acres=1000, aph_yield_bushels=200, trend_yield_bushels=205)
        policy = get_success_data(api.create_policy(
            create_policy_payload(op["id"], baseline["id"], coverage_level_pct=0.75, projected_price=4.50),
            ADVISOR,
        ))
        bound = get_success_data(api.bind_policy(policy["id"], make_grower_headers(op["id"])))
        assert bound["guarantee_bushels"] == 150000, (
            f"floor(200000 * 0.75) frozen at bind must be 150000, got {bound['guarantee_bushels']}"
        )
        settled = get_success_data(api.file_claim(
            policy["id"], {"actual_harvested_bushels": 140000, "harvest_price": 4.80},
            make_grower_headers(op["id"]),
        ))
        assert settled["status"] == "CLAIM_SETTLED"
        assert settled["indemnity_dollars"] == pytest.approx(48000.00, abs=0.005), (
            "(150000 - 140000) * max(4.50, 4.80) == 48000.00; got "
            f"{settled['indemnity_dollars']}"
        )
        operation = get_success_data(api.get_operation(op["id"], ADVISOR))
        assert operation["over_sold_flag"] is False, "no contracts outstanding — the tripwire stays down"

    def test_indemnity_zero_when_harvest_meets_guarantee(self, api):
        """PRD §3.2: "The `indemnity_dollars` are computed and frozen as the
        shortfall — the greater of zero and the guarantee minus the actual
        harvest — multiplied by the greater of `projected_price` and
        `harvest_price`, rounded to two decimal places half-up."

        Design: Corner/calculations/indemnity_zero_when_harvest_meets_guarantee
        """
        op = create_operation(
            name="Ins Farm 2", primary_commodity="CORN", crop_year=2026,
            risk_profile="BALANCED", yield_method="APH",
        )
        baseline = create_certified_baseline(op, planted_acres=1000, aph_yield_bushels=200, trend_yield_bushels=205)
        policy = get_success_data(api.create_policy(
            create_policy_payload(op["id"], baseline["id"], coverage_level_pct=0.75, projected_price=4.50),
            ADVISOR,
        ))
        get_success_data(api.bind_policy(policy["id"], make_grower_headers(op["id"])))
        settled = get_success_data(api.file_claim(
            policy["id"], {"actual_harvested_bushels": 150000, "harvest_price": 4.30},
            make_grower_headers(op["id"]),
        ))
        assert settled["indemnity_dollars"] == pytest.approx(0.00, abs=0.005), (
            "actual harvest exactly equal to the 150000 guarantee pays zero at the boundary"
        )


class TestOverSoldTripwire:
    def test_claim_trips_flag_and_blocks_new_contract(self, api):
        """PRD §3.2: "Settling a claim also evaluates the operation's over-sold
        tripwire: if the sum of undelivered committed bushels — that is,
        `bushels` minus `delivered_bushels` taken over the operation's `OPEN`
        and `PARTIALLY_DELIVERED` sales contracts — exceeds the settled
        `actual_harvested_bushels`, the operation's `over_sold_flag` is set to
        true. While that flag is set, new sales contracts are rejected with
        `ERR_OVER_SOLD_POSITION` and hedge-recommendation acceptances are
        rejected with the same code, until undelivered commitments once again
        fit within marketable production."

        Design: Corner/calculations/over_sold_flag_blocks_then_clears_on_cancel
        """
        ctx = setup_active_plan_with_buyer(
            name="OverSold Farm", risk_profile="BALANCED", planted_acres=1000, max_priced_pct=0.80
        )
        op_id = ctx["operation"]["id"]
        create_flat_contract(ctx, bushels=100000, fixed_price=4.50,
                             delivery_window_start="2026-10-01", delivery_window_end="2026-11-01")
        create_flat_contract(ctx, bushels=60000, fixed_price=4.55,
                             delivery_window_start="2026-11-01", delivery_window_end="2026-12-01")
        policy = get_success_data(api.create_policy(
            create_policy_payload(op_id, ctx["baseline"]["id"], coverage_level_pct=0.75, projected_price=4.50),
            ADVISOR,
        ))
        get_success_data(api.bind_policy(policy["id"], make_grower_headers(op_id)))
        get_success_data(api.file_claim(
            policy["id"], {"actual_harvested_bushels": 140000, "harvest_price": 4.80},
            make_grower_headers(op_id),
        ))
        operation = get_success_data(api.get_operation(op_id, ADVISOR))
        assert operation["over_sold_flag"] is True, (
            "160000 undelivered > 140000 settled harvest — the tripwire must engage"
        )
        resp = api.create_contract(
            create_contract_payload(
                op_id, ctx["plan"]["id"], ctx["buyer"]["id"],
                bushels=1000, fixed_price=4.60,
                delivery_window_start="2026-12-01", delivery_window_end="2027-01-01",
            ),
            ADVISOR,
        )
        validate_error(resp, ApiErrorId.ERR_OVER_SOLD_POSITION)

    def test_cancel_clears_flag_and_restores_sales(self, api):
        """PRD §3.2: "While that flag is set, new sales contracts are rejected
        with `ERR_OVER_SOLD_POSITION` and hedge-recommendation acceptances are
        rejected with the same code, until undelivered commitments once again
        fit within marketable production."
        PRD §3.7: "Cancellation moves an `OPEN` contract with zero delivered
        bushels to `CANCELLED`, releasing the full commitment back to the
        plan's `uncommitted_bushels`, recomputing `priced_contract_bushels`,
        and re-evaluating the operation's `over_sold_flag`, clearing it when
        undelivered committed bushels once again fit marketable production."

        Design: Corner/calculations/over_sold_flag_blocks_then_clears_on_cancel
        """
        ctx = setup_active_plan_with_buyer(
            name="OverSold Farm", risk_profile="BALANCED", planted_acres=1000, max_priced_pct=0.80
        )
        op_id = ctx["operation"]["id"]
        create_flat_contract(ctx, bushels=100000, fixed_price=4.50,
                             delivery_window_start="2026-10-01", delivery_window_end="2026-11-01")
        c2 = create_flat_contract(ctx, bushels=60000, fixed_price=4.55,
                                  delivery_window_start="2026-11-01", delivery_window_end="2026-12-01")
        policy = get_success_data(api.create_policy(
            create_policy_payload(op_id, ctx["baseline"]["id"], coverage_level_pct=0.75, projected_price=4.50),
            ADVISOR,
        ))
        get_success_data(api.bind_policy(policy["id"], make_grower_headers(op_id)))
        get_success_data(api.file_claim(
            policy["id"], {"actual_harvested_bushels": 140000, "harvest_price": 4.80},
            make_grower_headers(op_id),
        ))
        assert get_success_data(api.get_operation(op_id, ADVISOR))["over_sold_flag"] is True
        get_success_data(api.cancel_contract(c2["id"], ADVISOR))
        operation = get_success_data(api.get_operation(op_id, ADVISOR))
        assert operation["over_sold_flag"] is False, (
            "cancelling the 60000-bu contract brings undelivered to 100000 <= 140000 — flag auto-clears"
        )
        created = api.create_contract(
            create_contract_payload(
                op_id, ctx["plan"]["id"], ctx["buyer"]["id"],
                bushels=1000, fixed_price=4.60,
                delivery_window_start="2026-12-01", delivery_window_end="2027-01-01",
            ),
            ADVISOR,
        )
        validate_success(created, expected_status=201)
