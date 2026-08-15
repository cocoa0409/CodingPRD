"""Change orders: pricing tiers, negotiation cycle, OCC ledger, compensations."""
import pytest

from test_helpers import (
    ApiErrorId,
    approve_change_order_as_customer,
    assert_job_ledger_invariant,
    create_change_order_payload,
    get_success_data,
    make_customer_headers,
    new_change_order,
    new_customer,
    new_job,
    validate_error,
    validate_success,
)


class TestChangeOrderPricing:
    def test_change_order_tier_floor_overrides_smaller_discount(self, api, pm_headers):
        """PRD §3.8: "The volume-discount tier is keyed on the order's pre-discount
        `price_delta_cents`: below `100000` cents the tier is `T0`, from `100000` up
        to but not including `500000` cents the tier is `T1`, and `500000` cents or
        more the tier is `T2`. The effective discount is the maximum of the supplied
        `discount_pct` and the tier floor — `0.00` for `T0`, `0.05` for `T1`, `0.10`
        for `T2`. When `price_delta_cents` is non-negative, `computed_delta_cents` is
        the price delta multiplied by one minus the effective discount, rounded
        half-up to integer cents."

        Design: Difficulty/combinatorial_formula/change_order_pricing_circular_tier_pin_mode_c
        """
        customer = new_customer(company_name="Gamma Metals")
        job = new_job(customer["id"], job_number="J-3001", quoted_price_cents=1000000)
        order = new_change_order(job["id"], description="add remote I/O rack",
                                 price_delta_cents=200000, discount_pct=0.02)
        assert order["computed_delta_cents"] == 190000, (
            f"T1 floor 0.05 overrides the requested 0.02: 200000 * 0.95 = 190000, got "
            f"{order['computed_delta_cents']}"
        )

    def test_change_order_credit_passes_through_undiscounted(self, api, pm_headers):
        """PRD §3.8: "When `price_delta_cents` is negative — a credit back to the
        customer — the credit passes through undiscounted: `computed_delta_cents`
        equals `price_delta_cents` exactly, because a discount never deepens a
        credit."

        Design: Difficulty/combinatorial_formula/change_order_pricing_circular_tier_pin_mode_c
        """
        customer = new_customer(company_name="Gamma Metals")
        job = new_job(customer["id"], job_number="J-3001", quoted_price_cents=1000000)
        order = new_change_order(job["id"], description="de-scope spare pilot devices",
                                 price_delta_cents=-50000, discount_pct=0.30)
        assert order["computed_delta_cents"] == -50000, (
            f"credits pass through undiscounted, got {order['computed_delta_cents']}"
        )


class TestNegotiationCycle:
    def _setup(self, api):
        customer = new_customer(company_name="Eta Wire")
        job = new_job(customer["id"], job_number="J-6002", quoted_price_cents=1000000)
        order = new_change_order(job["id"], description="add surge protection",
                                 price_delta_cents=200000, discount_pct=0.02)
        return customer, job, order

    def test_change_order_revise_recomputes_delta_each_round(self, api, pm_headers):
        """PRD §3.8: "The customer counter-offers via the revise action, which the
        owning `Customer` performs against a `PROPOSED` order with a new
        `price_delta_cents` and optionally a new `discount_pct`; revise recomputes
        `computed_delta_cents` and increments the order's `version`."

        Design: Difficulty/non_linear_state_machine/change_order_cyclic_negotiation_proposed_revised
        """
        customer, _job, order = self._setup(api)
        cust = make_customer_headers(customer["id"])
        revised = validate_success(
            api.revise_change_order(
                order["id"], {"price_delta_cents": 180000, "discount_pct": 0.0}, cust
            ),
            200,
        )
        assert revised["status"] == "REVISED"
        assert revised["computed_delta_cents"] == 171000, (
            f"round-1 revise: 180000 * (1 - 0.05 T1 floor) = 171000, got "
            f"{revised['computed_delta_cents']}"
        )
        reproposed = validate_success(api.repropose_change_order(order["id"], pm_headers), 200)
        assert reproposed["status"] == "PROPOSED"

    def test_change_order_two_revise_cycles_then_approved(self, api, pm_headers):
        """PRD §3.8: "The `ProjectManager` accepts the counter by re-proposing,
        transitioning `REVISED → PROPOSED` and incrementing the version."
        PRD §3.8: "On a successful approval, the order's `computed_delta_cents` is
        added to the job's `approved_co_delta_cents`, the job's `contract_price_cents`
        is recomputed as `quoted_price_cents` plus `approved_co_delta_cents`, the
        job's `version` increments by one (it is the OCC anchor), the order's
        `version` increments by one, and the order transitions to `APPROVED`."

        Design: Difficulty/non_linear_state_machine/change_order_cyclic_negotiation_proposed_revised
        """
        customer, job, order = self._setup(api)
        cust = make_customer_headers(customer["id"])
        get_success_data(
            api.revise_change_order(order["id"],
                                    {"price_delta_cents": 180000, "discount_pct": 0.0}, cust),
            200,
        )
        get_success_data(api.repropose_change_order(order["id"], pm_headers), 200)
        round2 = validate_success(
            api.revise_change_order(order["id"],
                                    {"price_delta_cents": 150000, "discount_pct": 0.0}, cust),
            200,
        )
        assert round2["status"] == "REVISED"
        assert round2["computed_delta_cents"] == 142500, (
            f"round-2 revise: 150000 * (1 - 0.05 T1 floor) = 142500, got "
            f"{round2['computed_delta_cents']}"
        )

        approved = approve_change_order_as_customer(order["id"], customer["id"])
        assert approved["status"] == "APPROVED"
        assert approved["computed_delta_cents"] == 142500

        job_after = validate_success(api.get_job(job["id"], pm_headers), 200)
        assert job_after["approved_co_delta_cents"] == 142500
        assert job_after["contract_price_cents"] == 1142500
        assert_job_ledger_invariant(job_after)


class TestLedgerConservation:
    def _setup_two_approved(self, api):
        customer = new_customer(company_name="Sigma Frozen")
        job = new_job(customer["id"], job_number="J-9401", quoted_price_cents=1000000)
        co1 = new_change_order(job["id"], description="CO1 add UPS", price_delta_cents=120000)
        co2 = new_change_order(job["id"], description="CO2 add beacon", price_delta_cents=50000)
        return customer, job, co1, co2

    def test_two_approvals_accumulate_ledger(self, api, pm_headers):
        """PRD §3.8: "On a successful approval, the order's `computed_delta_cents` is
        added to the job's `approved_co_delta_cents`, the job's `contract_price_cents`
        is recomputed as `quoted_price_cents` plus `approved_co_delta_cents`, the
        job's `version` increments by one (it is the OCC anchor)".

        Design: Difficulty/compensating_invariant/change_order_approve_rescind_ledger_conservation
        """
        customer, job, co1, co2 = self._setup_two_approved(api)
        approve_change_order_as_customer(co1["id"], customer["id"])
        mid = validate_success(api.get_job(job["id"], pm_headers), 200)
        assert mid["approved_co_delta_cents"] == 114000, (
            f"CO1: 120000 * (1 - 0.05) = 114000, got {mid['approved_co_delta_cents']}"
        )
        assert_job_ledger_invariant(mid)

        approve_change_order_as_customer(co2["id"], customer["id"])
        after = validate_success(api.get_job(job["id"], pm_headers), 200)
        assert after["approved_co_delta_cents"] == 164000, (
            f"114000 + 50000 = 164000, got {after['approved_co_delta_cents']}"
        )
        assert after["contract_price_cents"] == 1164000
        assert_job_ledger_invariant(after)

    def test_rescind_subtracts_exact_computed_delta(self, api, pm_headers):
        """PRD §3.8: "On success, the order's `computed_delta_cents` is subtracted
        from the job's `approved_co_delta_cents` as a compensating entry,
        `contract_price_cents` is recomputed, the job's `version` increments, the
        order transitions `APPROVED → SUPERSEDED`, and the order's `version`
        increments."

        Design: Difficulty/compensating_invariant/change_order_approve_rescind_ledger_conservation
        """
        customer, job, co1, co2 = self._setup_two_approved(api)
        approve_change_order_as_customer(co1["id"], customer["id"])
        approve_change_order_as_customer(co2["id"], customer["id"])

        job_now = validate_success(api.get_job(job["id"], pm_headers), 200)
        rescinded = validate_success(
            api.rescind_change_order(
                co1["id"], {"expected_job_version": job_now["version"]}, pm_headers
            ),
            200,
        )
        assert rescinded["status"] == "SUPERSEDED"

        after = validate_success(api.get_job(job["id"], pm_headers), 200)
        assert after["approved_co_delta_cents"] == 50000, (
            f"compensation subtracts exactly the rescinded delta: 164000 - 114000 = 50000, "
            f"got {after['approved_co_delta_cents']}"
        )
        assert after["contract_price_cents"] == 1050000
        assert_job_ledger_invariant(after)

        co2_after = validate_success(api.get_change_order(co2["id"], pm_headers), 200)
        assert co2_after["status"] == "APPROVED", "the other approval is untouched"


class TestInvalidStateBeatsCreditHold:
    def _setup(self, api, pm_headers):
        customer = new_customer(company_name="Kappa Dairy")
        job = new_job(customer["id"], job_number="J-9001", quoted_price_cents=1000000)
        order = new_change_order(job["id"], description="scope add A",
                                 price_delta_cents=120000)
        approve_change_order_as_customer(order["id"], customer["id"])
        get_success_data(
            api.update_customer(customer["id"], {"credit_hold": True}, pm_headers), 200
        )
        return customer, job, order

    def test_reapprove_approved_co_under_credit_hold_reports_invalid_state(self, api,
                                                                           pm_headers):
        """PRD §2.9: "When a request fails more than one validation, the server
        reports the failure with the lowest priority number."
        PRD §2.9: "6. `ERR_INVALID_STATE` — target entity not in a state from which
        the requested transition is defined." and "17. `ERR_CREDIT_HOLD` — customer
        credit hold blocking job creation, job advance, substitution approval, or
        change-order approval."

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_credit_hold_on_co_approve
        """
        customer, job, order = self._setup(api, pm_headers)
        job_now = validate_success(api.get_job(job["id"], pm_headers), 200)
        resp = api.approve_change_order(
            order["id"],
            {"expected_job_version": job_now["version"]},
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_rejected_reapprove_leaves_ledger_unchanged(self, api, pm_headers):
        """PRD §3.8: "On a successful approval, the order's `computed_delta_cents` is
        added to the job's `approved_co_delta_cents`" — a rejected approval performs
        no such addition, so the ledger stays exactly where the first approval left
        it.
        PRD §2.9: "When a request fails more than one validation, the server reports
        the failure with the lowest priority number."

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_credit_hold_on_co_approve
        """
        customer, job, order = self._setup(api, pm_headers)
        job_now = validate_success(api.get_job(job["id"], pm_headers), 200)
        validate_error(
            api.approve_change_order(
                order["id"],
                {"expected_job_version": job_now["version"]},
                make_customer_headers(customer["id"]),
            ),
            ApiErrorId.ERR_INVALID_STATE,
            409,
        )
        after = validate_success(api.get_job(job["id"], pm_headers), 200)
        assert after["approved_co_delta_cents"] == 114000
        assert after["contract_price_cents"] == 1114000
        order_after = validate_success(api.get_change_order(order["id"], pm_headers), 200)
        assert order_after["status"] == "APPROVED"


class TestApproveRbacAndOwnership:
    def test_shipping_clerk_cannot_approve_change_order(self, api, pm_headers,
                                                        shipping_headers):
        """PRD §2.1: "A request whose role is authenticated but not listed in the
        target endpoint's Authorized Role(s) column is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §2.9: "So, for example, a `ChangeOrder` approval that fails both RBAC and
        OCC reports `ERR_UNAUTHORIZED`, not `ERR_STALE_VERSION`".

        Design: Corner/rbac/shipping_clerk_cannot_approve_change_order
        """
        customer = new_customer(company_name="SC Co")
        job = new_job(customer["id"], job_number="J-SC1", quoted_price_cents=100)
        order = new_change_order(job["id"], description="rbac probe",
                                 price_delta_cents=1000)
        resp = api.approve_change_order(
            order["id"], {"expected_job_version": 1}, shipping_headers
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
        after = validate_success(api.get_change_order(order["id"], pm_headers), 200)
        assert after["status"] == "PROPOSED"

    def test_customer_ownership_required_on_change_order_approve(self, api, pm_headers):
        """PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of
        the acting `Customer` record; ownership checks on any `Job`, `ChangeOrder`,
        or `SubstitutionRequest` compare the resource's `customer_id` foreign key (or
        the customer of the owning chain) to `X-User-ID`, and a mismatch is rejected
        with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/rbac/customer_ownership_required_on_change_order_approve
        """
        owner = new_customer(company_name="Own A")
        intruder = new_customer(company_name="Own B")
        job = new_job(owner["id"], job_number="J-OW1", quoted_price_cents=100)
        order = new_change_order(job["id"], description="ownership probe",
                                 price_delta_cents=1000)
        job_now = validate_success(api.get_job(job["id"], pm_headers), 200)
        resp = api.approve_change_order(
            order["id"],
            {"expected_job_version": job_now["version"]},
            make_customer_headers(intruder["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)
        after = validate_success(api.get_change_order(order["id"], pm_headers), 200)
        assert after["status"] == "PROPOSED"


class TestDerivedPriceReconciliation:
    def test_derived_contract_price_reconciles_after_each_ledger_mutation(self, api,
                                                                          pm_headers):
        """PRD §3.8: "On a successful approval, the order's `computed_delta_cents` is
        added to the job's `approved_co_delta_cents`, the job's `contract_price_cents`
        is recomputed as `quoted_price_cents` plus `approved_co_delta_cents`".
        PRD §3.8: "A `Job` read exposes `contract_price_cents` directly so a client
        can always see the current ledger."

        Design: Corner/cross_cutting_layers/derived_contract_price_reconciles_after_each_ledger_mutation
        """
        customer = new_customer(company_name="DF Co")
        job = validate_success(
            api.create_job(
                {"customer_id": customer["id"], "job_number": "J-DF1",
                 "quoted_price_cents": 1000000},
                pm_headers,
            ),
            201,
        )
        assert job["contract_price_cents"] == 1000000, (
            f"no orders yet: contract == quoted, got {job['contract_price_cents']}"
        )
        assert_job_ledger_invariant(job)

        order = new_change_order(job["id"], description="recon probe",
                                 price_delta_cents=120000)
        approve_change_order_as_customer(order["id"], customer["id"])
        after = validate_success(api.get_job(job["id"], pm_headers), 200)
        assert after["approved_co_delta_cents"] == 114000
        assert after["contract_price_cents"] == 1114000
        assert_job_ledger_invariant(after)

    def test_immediate_consistency_post_response_reflects_all_side_effects(self, api,
                                                                           pm_headers):
        """PRD §3.8: "On a successful approval, the order's `computed_delta_cents` is
        added to the job's `approved_co_delta_cents`, the job's `contract_price_cents`
        is recomputed as `quoted_price_cents` plus `approved_co_delta_cents`, the
        job's `version` increments by one (it is the OCC anchor), the order's
        `version` increments by one, and the order transitions to `APPROVED`."
        PRD §3.8: "A `Job` read exposes `contract_price_cents` directly so a client
        can always see the current ledger."

        Design: Corner/consistency_model/immediate_consistency_post_response_reflects_all_side_effects
        """
        customer = new_customer(company_name="IC Co")
        job = new_job(customer["id"], job_number="J-IC1", quoted_price_cents=1000000)
        order = new_change_order(job["id"], description="consistency probe",
                                 price_delta_cents=120000)
        cust = make_customer_headers(customer["id"])
        job_now = validate_success(api.get_job(job["id"], pm_headers), 200)
        approved = validate_success(
            api.approve_change_order(
                order["id"], {"expected_job_version": job_now["version"]}, cust
            ),
            200,
        )
        assert approved["status"] == "APPROVED", (
            "the mutation response itself carries the post-approval state"
        )

        ledger = validate_success(api.get_job(job["id"], cust), 200)
        assert ledger["approved_co_delta_cents"] == 114000, (
            f"immediately-following read shows the posted ledger, got "
            f"{ledger['approved_co_delta_cents']}"
        )
        assert_job_ledger_invariant(ledger)
