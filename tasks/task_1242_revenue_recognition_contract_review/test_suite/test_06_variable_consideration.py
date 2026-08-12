"""Variable consideration: estimation, constraint, and approval (PRD §3.5)."""
import pytest

from test_helpers import (
    ApiErrorId, validate_success, validate_error, validate_paginated,
    create_customer, create_contract, create_vc_estimate_payload, get_contract,
    make_accountant_headers, make_manager_headers,
    assert_vc_estimate,
)

EV_SCENARIOS = [
    {"probability_bps": 3000, "amount_cents": 100000},
    {"probability_bps": 5000, "amount_cents": 60000},
    {"probability_bps": 2000, "amount_cents": 20000},
]


def _draft_contract(risk_tier="STANDARD", fixed=0, ref=None):
    customer = create_customer()
    kwargs = {"risk_tier": risk_tier, "fixed_consideration_cents": fixed}
    if ref:
        kwargs["contract_ref"] = ref
    return create_contract(customer["id"], **kwargs)


class TestDualVariantEstimate:
    def test_expected_value_weighted_mean_and_cap(self, api, accountant_headers):
        """PRD §3.5: "Under `EXPECTED_VALUE`, `unconstrained_amount_cents` is
        the probability-weighted mean: each scenario's `amount_cents` is
        multiplied by its `probability_bps`, the products are summed, the sum is
        divided by ten thousand, and the quotient is rounded half up to whole
        cents."
        PRD §3.5: "The constraint then caps the includable amount by the
        contract's `risk_tier`: 85 percent for `STANDARD`, 70 percent for
        `ELEVATED`, and 50 percent for `HIGH`."

        Design: Difficulty/dual_variant_calc/vc_estimate_expected_value_vs_most_likely
        """
        contract = _draft_contract(risk_tier="STANDARD", fixed=1000000, ref="C-VC-EV")
        resp = api.create_vc_estimate(
            contract["id"],
            create_vc_estimate_payload(method="EXPECTED_VALUE", scenarios=EV_SCENARIOS),
            accountant_headers,
        )
        est = validate_success(resp, 201)
        assert_vc_estimate(est)
        assert est["unconstrained_amount_cents"] == 64000
        assert est["constrained_amount_cents"] == 54400
        assert est["status"] == "PROPOSED"

    def test_most_likely_picks_modal_scenario(self, api, accountant_headers):
        """PRD §3.5: "Under `MOST_LIKELY`, the system selects the single
        scenario with the greatest `probability_bps` — ties are broken by the
        earliest position in the array, and random ids never participate in the
        tie-break — and that scenario's `amount_cents` becomes the unconstrained
        amount, with every other scenario ignored. Identical scenario sets
        therefore generally yield different unconstrained amounts under the two
        methods."

        Design: Difficulty/dual_variant_calc/vc_estimate_expected_value_vs_most_likely
        """
        contract = _draft_contract(risk_tier="STANDARD", fixed=1000000, ref="C-VC-ML")
        resp = api.create_vc_estimate(
            contract["id"],
            create_vc_estimate_payload(method="MOST_LIKELY", scenarios=EV_SCENARIOS),
            accountant_headers,
        )
        est = validate_success(resp, 201)
        assert est["unconstrained_amount_cents"] == 60000
        assert est["constrained_amount_cents"] == 51000

    def test_methods_diverge_on_identical_scenarios(self, api, accountant_headers):
        """PRD §3.5: "Identical scenario sets therefore generally yield
        different unconstrained amounts under the two methods."

        Design: Difficulty/dual_variant_calc/vc_estimate_expected_value_vs_most_likely
        """
        contract = _draft_contract(risk_tier="STANDARD", fixed=1000000, ref="C-VC-BOTH")
        ev = validate_success(api.create_vc_estimate(
            contract["id"],
            create_vc_estimate_payload(method="EXPECTED_VALUE", scenarios=EV_SCENARIOS),
            accountant_headers,
        ), 201)
        ml = validate_success(api.create_vc_estimate(
            contract["id"],
            create_vc_estimate_payload(method="MOST_LIKELY", scenarios=EV_SCENARIOS),
            accountant_headers,
        ), 201)
        assert ev["unconstrained_amount_cents"] == 64000
        assert ml["unconstrained_amount_cents"] == 60000
        assert ev["constrained_amount_cents"] != ml["constrained_amount_cents"], (
            "identical scenario input must constrain to different amounts across methods"
        )


class TestTieredConstraintCaps:
    @pytest.mark.parametrize("tier,expected_constrained", [
        ("STANDARD", 85000),
        ("ELEVATED", 70000),
        ("HIGH", 50000),
    ])
    def test_cap_by_risk_tier(self, api, accountant_headers, tier, expected_constrained):
        """PRD §3.5: "The constraint then caps the includable amount by the
        contract's `risk_tier`: 85 percent for `STANDARD`, 70 percent for
        `ELEVATED`, and 50 percent for `HIGH`. The `constrained_amount_cents` is
        the smaller of the unconstrained amount and the unconstrained amount
        multiplied by the tier's cap and rounded down to whole cents."

        Design: Difficulty/combinatorial_formula/vc_constraint_tiered_caps
        """
        contract = _draft_contract(risk_tier=tier, fixed=0, ref=f"C-{tier}")
        est = validate_success(api.create_vc_estimate(
            contract["id"],
            create_vc_estimate_payload(
                method="MOST_LIKELY",
                scenarios=[{"probability_bps": 10000, "amount_cents": 100000}],
            ),
            accountant_headers,
        ), 201)
        assert est["unconstrained_amount_cents"] == 100000
        assert est["constrained_amount_cents"] == expected_constrained

    def test_cap_term_floored_to_whole_cents(self, api, accountant_headers):
        """PRD §2.6: "Where a rule calls for a floor instead, it says so
        explicitly: the variable-consideration constraint of §3.5 rounds the cap
        term down to whole cents."
        PRD §3.5: "The comparison is inclusive: when the rounded-down cap term
        equals the unconstrained amount, the full unconstrained amount is
        includable."

        Design: Difficulty/combinatorial_formula/vc_constraint_tiered_caps
        """
        # floor(999 * 0.70) == 699 < 999 -> capped at 699 (floor, not round-up 700).
        contract = _draft_contract(risk_tier="ELEVATED", fixed=0, ref="C-FLOOR")
        est = validate_success(api.create_vc_estimate(
            contract["id"],
            create_vc_estimate_payload(
                method="MOST_LIKELY",
                scenarios=[{"probability_bps": 10000, "amount_cents": 999}],
            ),
            accountant_headers,
        ), 201)
        assert est["constrained_amount_cents"] == 699


class TestScenarioWeightsBoundary:
    def test_weights_9999_rejected(self, api, accountant_headers):
        """PRD §3.5: "The weights across the array must sum to exactly ten
        thousand basis points — one hundred percent — or the proposal is
        rejected with `ERR_SCENARIO_WEIGHTS` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/boundary_vc_scenario_weights_exactly_10000
        """
        contract = _draft_contract(ref="C-BND")
        resp = api.create_vc_estimate(
            contract["id"],
            create_vc_estimate_payload(
                method="EXPECTED_VALUE",
                scenarios=[{"probability_bps": 5000, "amount_cents": 100000},
                           {"probability_bps": 4999, "amount_cents": 50000}],
            ),
            accountant_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SCENARIO_WEIGHTS, 422)

    def test_weights_exactly_10000_accepted(self, api, accountant_headers):
        """PRD §3.5: "The weights across the array must sum to exactly ten
        thousand basis points — one hundred percent — or the proposal is
        rejected with `ERR_SCENARIO_WEIGHTS` (HTTP 422)."
        PRD §3.5: "A new estimate starts `PROPOSED`, with `proposed_by_user_id`
        recorded from the creator's `X-User-ID` and `approved_by_user_id` null."

        Design: Difficulty/boundary_precision_check/boundary_vc_scenario_weights_exactly_10000
        """
        contract = _draft_contract(ref="C-BND-OK")
        est = validate_success(api.create_vc_estimate(
            contract["id"],
            create_vc_estimate_payload(
                method="EXPECTED_VALUE",
                scenarios=[{"probability_bps": 5000, "amount_cents": 100000},
                           {"probability_bps": 5000, "amount_cents": 50000}],
            ),
            accountant_headers,
        ), 201)
        # EV: (5000*100000 + 5000*50000)/10000 = 75000; STANDARD cap: floor(63750.0) = 63750.
        assert est["unconstrained_amount_cents"] == 75000
        assert est["constrained_amount_cents"] == 63750
        assert est["status"] == "PROPOSED"
        assert est["proposed_by_user_id"] == "acct-1"
        assert est["approved_by_user_id"] is None


class TestEstimateApproval:
    def test_approve_by_proposer_returns_sod_violation(self, api):
        """PRD §2.10: "A variable consideration estimate may not be approved by
        the operator who proposed it — the approver's `X-User-ID` must differ
        from the estimate's `proposed_by_user_id`."
        PRD §2.10: "all four pairings fail with the same `ERR_SOD_VIOLATION`
        (HTTP 409)".

        Design: Corner/validations/estimate_approve_by_proposer_returns_sod_violation
        """
        customer = create_customer()
        dual = make_accountant_headers("dual-1")
        contract = validate_success(api.create_contract(
            {"customer_id": customer["id"], "contract_ref": "C-SODE",
             "signed_date": "2026-05-20", "fixed_consideration_cents": 0,
             "risk_tier": "STANDARD"}, dual,
        ), 201)
        est = validate_success(api.create_vc_estimate(
            contract["id"], create_vc_estimate_payload(), dual,
        ), 201)
        resp = api.approve_vc_estimate(est["id"], make_manager_headers("dual-1"))
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION, 409)

    def test_estimate_stays_proposed_after_sod_rejection(self, api):
        """PRD §2.10: "A variable consideration estimate may not be approved by
        the operator who proposed it — the approver's `X-User-ID` must differ
        from the estimate's `proposed_by_user_id`."

        Design: Corner/validations/estimate_approve_by_proposer_returns_sod_violation
        """
        customer = create_customer()
        dual = make_accountant_headers("dual-2")
        contract = validate_success(api.create_contract(
            {"customer_id": customer["id"], "contract_ref": "C-SODE2",
             "signed_date": "2026-05-20", "fixed_consideration_cents": 0,
             "risk_tier": "STANDARD"}, dual,
        ), 201)
        est = validate_success(api.create_vc_estimate(
            contract["id"], create_vc_estimate_payload(), dual,
        ), 201)
        validate_error(api.approve_vc_estimate(est["id"], make_manager_headers("dual-2")),
                       ApiErrorId.ERR_SOD_VIOLATION, 409)
        listed = validate_paginated(
            api.list_vc_estimates(contract["id"], make_manager_headers("mgr-9"))
        )[0]
        assert listed[0]["id"] == est["id"]
        assert listed[0]["status"] == "PROPOSED"

    def test_newer_estimate_approval_supersedes_prior(self, api, manager_headers, accountant_headers):
        """PRD §3.5: "Any previously `APPROVED` estimate of the same contract
        becomes `SUPERSEDED`. The contract's `active_vc_estimate_id` is set to
        the newly approved estimate, its `vc_estimate_cents` becomes the
        estimate's `constrained_amount_cents`, its `transaction_price_cents` is
        recomputed as fixed plus variable".

        Design: Corner/state_machines/newer_estimate_approval_supersedes_prior
        """
        customer = create_customer(legal_name="Sup Co", external_ref="SUP-1")
        contract = create_contract(customer["id"], contract_ref="C-SUP",
                                   fixed_consideration_cents=25000)
        e1 = validate_success(api.create_vc_estimate(
            contract["id"], create_vc_estimate_payload(), accountant_headers,
        ), 201)
        validate_success(api.approve_vc_estimate(e1["id"], manager_headers))

        e2 = validate_success(api.create_vc_estimate(
            contract["id"],
            create_vc_estimate_payload(
                scenarios=[{"probability_bps": 10000, "amount_cents": 40000}]),
            accountant_headers,
        ), 201)
        validate_success(api.approve_vc_estimate(e2["id"], manager_headers))

        superseded = validate_paginated(api.list_vc_estimates(
            contract["id"], manager_headers, params={"status": "SUPERSEDED"}
        ))[0]
        assert [e["id"] for e in superseded] == [e1["id"]]

        contract_after = get_contract(contract["id"])
        assert contract_after["active_vc_estimate_id"] == e2["id"]
        assert contract_after["vc_estimate_cents"] == 34000
        assert contract_after["transaction_price_cents"] == 59000

    def test_approval_bumps_contract_version(self, api, manager_headers, accountant_headers):
        """PRD §2.4: "submitting, returning, approving, activating, holding,
        resuming, cancelling, and absorbing a contract; proposing a modification
        and approving one; approving an estimate; issuing and voiding an
        invoice; and posting a reversal each increment the owning contract's
        `version` by one and refresh its `updated_at`."

        PRD §2.4 (contrasted rule): "Operations not named here — creating an
        obligation, a clause, an estimate, or a cost entry; satisfying or
        recognizing an obligation; assembling or finalizing a pack — do not, by
        themselves, increment the contract's `version`".

        Design: Corner/state_machines/newer_estimate_approval_supersedes_prior
        """
        customer = create_customer()
        contract = create_contract(customer["id"], fixed_consideration_cents=25000)
        assert contract["version"] == 1
        est = validate_success(api.create_vc_estimate(
            contract["id"], create_vc_estimate_payload(), accountant_headers,
        ), 201)
        # Creating an estimate does not itself bump the contract version (§2.4).
        assert get_contract(contract["id"])["version"] == 1
        validate_success(api.approve_vc_estimate(est["id"], manager_headers))
        assert get_contract(contract["id"])["version"] == 2
