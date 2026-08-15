"""Contract modifications: OCC guard, the three accounting treatments, and the
approval guards (PRD §2.7, §2.8, §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId, validate_success, validate_error, validate_paginated,
    create_customer, create_contract, create_modification_payload,
    create_period, set_clock, get_contract, get_pob,
    setup_active_contract_with_pob, setup_active_contract_with_pobs,
    propose_modification, get_contract_version,
    make_accountant_headers, make_manager_headers,
    assert_modification, TEST_USERS,
)

CLOCK = "2026-06-15T00:00:00Z"


class TestOccGuard:
    def _setup(self, api):
        return setup_active_contract_with_pob()

    def test_stale_version_rejected(self, api, accountant_headers):
        """PRD §2.7: "When the supplied value does not equal the contract's
        current `version`, the proposal is rejected with `ERR_STALE_VERSION`
        (HTTP 412)".

        Design: Corner/cross_cutting_layers/modification_create_with_stale_version_returns_412
        """
        contract = self._setup(api)["contract"]
        observed = get_contract_version(contract["id"])
        # First proposal at the observed version succeeds and bumps the version.
        validate_success(api.create_modification(
            contract["id"],
            create_modification_payload(observed, mod_type="PROSPECTIVE",
                                        delta_fixed_consideration_cents=10000),
            accountant_headers,
        ), 201)
        assert get_contract_version(contract["id"]) == observed + 1
        # Second proposal carrying the stale captured version is rejected.
        resp = api.create_modification(
            contract["id"],
            create_modification_payload(observed, mod_type="PROSPECTIVE",
                                        delta_fixed_consideration_cents=20000,
                                        effective_date="2026-06-16"),
            accountant_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

    def test_sequential_proposals_at_current_version_allowed(self, api, accountant_headers):
        """PRD §2.7: "it is not a mutual-exclusion lock on proposals. Several
        modifications may legitimately be proposed against the same `ACTIVE`
        contract, so a second, strictly sequential proposal is rejected only
        when it carries a stale `expected_contract_version`, never merely
        because an earlier proposal already exists."
        PRD §3.8: "because proposing a modification is itself a contract
        mutation — the act of proposing bumps the contract's `version`."

        Design: Corner/cross_cutting_layers/modification_create_with_stale_version_returns_412
        """
        contract = self._setup(api)["contract"]
        v1 = get_contract_version(contract["id"])
        m1 = validate_success(api.create_modification(
            contract["id"],
            create_modification_payload(v1, mod_type="PROSPECTIVE",
                                        delta_fixed_consideration_cents=10000),
            accountant_headers,
        ), 201)
        assert_modification(m1)
        assert m1["status"] == "PROPOSED"
        assert get_contract_version(contract["id"]) == v1 + 1
        v2 = get_contract_version(contract["id"])
        m2 = validate_success(api.create_modification(
            contract["id"],
            create_modification_payload(v2, mod_type="PROSPECTIVE",
                                        delta_fixed_consideration_cents=20000,
                                        effective_date="2026-06-16"),
            accountant_headers,
        ), 201)
        assert m2["id"] != m1["id"]
        listed = validate_paginated(
            api.list_modifications(contract["id"], accountant_headers))[0]
        assert len(listed) == 2


class TestModificationCreationStateGate:
    def test_create_on_draft_contract_rejected(self, api, accountant_headers):
        """PRD §3.8: "A `RevenueAccountant` proposes one against an `ACTIVE`
        contract — any other state fails with `ERR_CONTRACT_NOT_ACTIVE`".

        Design: Corner/validations/modification_create_on_draft_contract_rejected
        """
        customer = create_customer(legal_name="Draft Co", external_ref="DRAFT-1")
        contract = create_contract(customer["id"], contract_ref="C-DRAFT")
        resp = api.create_modification(
            contract["id"],
            create_modification_payload(contract["version"], mod_type="PROSPECTIVE",
                                        delta_fixed_consideration_cents=10000),
            accountant_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE, 409)

    def test_rejected_creation_persists_nothing(self, api, accountant_headers):
        """PRD §3.8: "A `RevenueAccountant` proposes one against an `ACTIVE`
        contract — any other state fails with `ERR_CONTRACT_NOT_ACTIVE`".

        Design: Corner/validations/modification_create_on_draft_contract_rejected
        """
        customer = create_customer()
        contract = create_contract(customer["id"])
        validate_error(api.create_modification(
            contract["id"],
            create_modification_payload(contract["version"], mod_type="PROSPECTIVE",
                                        delta_fixed_consideration_cents=10000),
            accountant_headers,
        ), ApiErrorId.ERR_CONTRACT_NOT_ACTIVE, 409)
        listed = validate_paginated(
            api.list_modifications(contract["id"], accountant_headers))[0]
        assert listed == [], "no modification may be persisted on a DRAFT contract"


class TestCatchUpPinnedOrder:
    def _setup(self, api, accountant_headers):
        setup = setup_active_contract_with_pob(
            pob_overrides={"recognition_pattern": "OVER_TIME_INPUT_COST",
                           "estimated_total_cost_cents": 40000},
        )
        pob = setup["pob"]
        # Recognize 50% of 100000 before the modification.
        validate_success(api.create_cost_entry(
            pob["id"], {"amount_cents": 20000, "incurred_date": "2026-06-10"},
            accountant_headers,
        ), 201)
        assert get_pob(pob["id"])["recognized_revenue_cents"] == 50000
        return setup

    def test_reallocation_before_target_computation(self, api, accountant_headers, manager_headers):
        """PRD §3.8: "First the delta is applied: `fixed_consideration_cents` is
        increased by `delta_fixed_consideration_cents`, and
        `transaction_price_cents` is recomputed. Second, the allocation
        waterfall of §3.4 re-runs over all non-`CANCELLED` obligations,
        redistributing the whole new transaction price."

        Design: Difficulty/combinatorial_formula/catch_up_pinned_evaluation_order
        """
        setup = self._setup(api, accountant_headers)
        contract, pob = setup["contract"], setup["pob"]
        mod = propose_modification(contract["id"], delta_fixed_consideration_cents=60000)
        validate_success(api.approve_modification(mod["id"], manager_headers))
        contract_after = get_contract(contract["id"])
        assert contract_after["fixed_consideration_cents"] == 160000
        assert contract_after["transaction_price_cents"] == 160000
        pob_after = get_pob(pob["id"])
        assert pob_after["allocated_amount_cents"] == 160000

    def test_single_signed_catch_up_entry(self, api, accountant_headers, manager_headers):
        """PRD §3.8: "Fifth, each obligation's target is recomputed as its new
        allocated amount multiplied by its ratio, rounded half up to whole
        cents. Sixth, the catch-up for each obligation is its target minus its
        `recognized_revenue_cents`. Seventh, one `CATCH_UP_ADJUSTMENT` entry
        with origin `MODIFICATION`, posting at the current clock date, is
        written per obligation whose catch-up is non-zero; obligations whose
        target did not move receive no entry."

        Design: Difficulty/combinatorial_formula/catch_up_pinned_evaluation_order
        """
        setup = self._setup(api, accountant_headers)
        contract, pob, period = setup["contract"], setup["pob"], setup["period"]
        mod = propose_modification(contract["id"], delta_fixed_consideration_cents=60000)
        validate_success(api.approve_modification(mod["id"], manager_headers))
        # target = round_half_up(160000 * 0.5) = 80000; catch-up = 80000 - 50000 = 30000.
        pob_after = get_pob(pob["id"])
        assert pob_after["recognized_revenue_cents"] == 80000
        entries = validate_paginated(api.list_revenue_entries(
            accountant_headers,
            params={"pob_id": pob["id"], "entry_type": "CATCH_UP_ADJUSTMENT"},
        ))[0]
        assert len(entries) == 1, "exactly one signed catch-up entry, not a re-posted target"
        assert entries[0]["amount_cents"] == 30000
        assert entries[0]["origin"] == "MODIFICATION"
        assert entries[0]["posting_date"] == "2026-06-15"
        # The period total reflects the full recognized amount.
        from test_helpers.fixtures import get_period
        assert get_period(period["id"])["recognized_total_cents"] == 80000

    def test_allocation_sum_conserved_across_catch_up(self, api, accountant_headers, manager_headers):
        """PRD §3.4: "After the residual lands, the allocated lines sum exactly
        to the transaction price, and the contract's `allocated_total_cents` is
        set to `transaction_price_cents`."

        Design: Difficulty/compensating_invariant/invariant_allocation_sum_conserved_across_modification
        """
        setup = setup_active_contract_with_pobs(
            [
                {"product_code": "QA", "ssp_cents": 300000, "pob": {"pob_ref": "PA"}},
                {"product_code": "QB", "ssp_cents": 500000, "pob": {"pob_ref": "PB"}},
            ],
            fixed=1000000,
        )
        contract = setup["contract"]
        pa, pb = setup["pobs"]
        assert get_pob(pa["id"])["allocated_amount_cents"] == 375000
        assert get_pob(pb["id"])["allocated_amount_cents"] == 625000
        assert get_contract(contract["id"])["allocated_total_cents"] == 1000000

        mod = propose_modification(contract["id"], delta_fixed_consideration_cents=250000)
        validate_success(api.approve_modification(mod["id"], manager_headers))
        # 1250000 * 3/8 = 468750 ; 1250000 * 5/8 = 781250.
        assert get_pob(pa["id"])["allocated_amount_cents"] == 468750
        assert get_pob(pb["id"])["allocated_amount_cents"] == 781250

    def test_contract_total_tracks_transaction_price(self, api, accountant_headers, manager_headers):
        """PRD §3.1: "The transaction price is at all times derived, never set
        directly: `transaction_price_cents` is the sum of
        `fixed_consideration_cents` and `vc_estimate_cents`".
        PRD §3.4: "the contract's `allocated_total_cents` is set to
        `transaction_price_cents`."

        Design: Difficulty/compensating_invariant/invariant_allocation_sum_conserved_across_modification
        """
        setup = setup_active_contract_with_pobs(
            [
                {"product_code": "QA", "ssp_cents": 300000, "pob": {"pob_ref": "PA"}},
                {"product_code": "QB", "ssp_cents": 500000, "pob": {"pob_ref": "PB"}},
            ],
            fixed=1000000,
        )
        contract = setup["contract"]
        mod = propose_modification(contract["id"], delta_fixed_consideration_cents=250000)
        validate_success(api.approve_modification(mod["id"], manager_headers))
        after = get_contract(contract["id"])
        assert after["transaction_price_cents"] == 1250000
        assert after["allocated_total_cents"] == 1250000
        pob_sum = sum(get_pob(p["id"])["allocated_amount_cents"] for p in setup["pobs"])
        assert pob_sum == after["transaction_price_cents"], (
            "allocated sum must be conserved across reallocation"
        )


class TestCatchUpCascade:
    def _setup(self, api, accountant_headers):
        """PX (input-cost, est 50000) + PY (straight-line 06-01..07-01)."""
        setup = setup_active_contract_with_pobs(
            [
                {"product_code": "PX", "ssp_cents": 100000,
                 "pob": {"pob_ref": "PX", "recognition_pattern": "OVER_TIME_INPUT_COST",
                         "estimated_total_cost_cents": 50000}},
                {"product_code": "PY", "ssp_cents": 300000,
                 "pob": {"pob_ref": "PY", "recognition_pattern": "OVER_TIME_STRAIGHT_LINE",
                         "service_start_date": "2026-06-01", "service_end_date": "2026-07-01"}},
            ],
            fixed=200000,
        )
        pob_x, pob_y = setup["pobs"]
        # PX: 25000/50000 = 50% of allocated 50000 -> recognized 25000.
        validate_success(api.create_cost_entry(
            pob_x["id"], {"amount_cents": 25000, "incurred_date": "2026-06-10"},
            accountant_headers,
        ), 201)
        # PY: 14/30 of allocated 150000 -> recognized 70000.
        validate_success(api.recognize_pob(pob_y["id"], accountant_headers))
        assert get_pob(pob_x["id"])["recognized_revenue_cents"] == 25000
        assert get_pob(pob_y["id"])["recognized_revenue_cents"] == 70000
        return setup

    def test_cascade_moves_allocations_and_posts_catchups(self, api, accountant_headers, manager_headers):
        """PRD §3.8: "Second, the allocation waterfall of §3.4 re-runs over all
        non-`CANCELLED` obligations, redistributing the whole new transaction
        price" and "Seventh, one `CATCH_UP_ADJUSTMENT` entry with origin
        `MODIFICATION`, posting at the current clock date, is written per
        obligation whose catch-up is non-zero".

        Design: Difficulty/transitive_cascade/cascade_modification_catchup_to_period_totals
        """
        setup = self._setup(api, accountant_headers)
        contract = setup["contract"]
        pob_x, pob_y = setup["pobs"]
        mod = propose_modification(contract["id"], delta_fixed_consideration_cents=200000)
        validate_success(api.approve_modification(mod["id"], manager_headers))
        contract_after = get_contract(contract["id"])
        assert contract_after["fixed_consideration_cents"] == 400000
        assert contract_after["transaction_price_cents"] == 400000
        # Reallocation: 400000 split 1:3 -> 100000 / 300000.
        assert get_pob(pob_x["id"])["allocated_amount_cents"] == 100000
        assert get_pob(pob_y["id"])["allocated_amount_cents"] == 300000
        # Catch-ups: PX target 50000 - 25000 = +25000; PY target 140000 - 70000 = +70000.
        x_entries = validate_paginated(api.list_revenue_entries(
            accountant_headers,
            params={"pob_id": pob_x["id"], "entry_type": "CATCH_UP_ADJUSTMENT"},
        ))[0]
        y_entries = validate_paginated(api.list_revenue_entries(
            accountant_headers,
            params={"pob_id": pob_y["id"], "entry_type": "CATCH_UP_ADJUSTMENT"},
        ))[0]
        assert [e["amount_cents"] for e in x_entries] == [25000]
        assert [e["amount_cents"] for e in y_entries] == [70000]

    def test_cascade_updates_period_and_contract_totals(self, api, accountant_headers, manager_headers):
        """PRD §3.9: "`recognized_total_cents` zero, the latter tracking the
        signed sum of the period's `POSTED` and `LOCKED` entries as they post."
        PRD §2.11: "`recognized_to_date_cents` is the sum of the signed
        `amount_cents` over the contract's revenue entries whose status is
        `POSTED` or `LOCKED`."

        Design: Difficulty/transitive_cascade/cascade_modification_catchup_to_period_totals
        """
        from test_helpers.fixtures import get_period
        setup = self._setup(api, accountant_headers)
        contract, period = setup["contract"], setup["period"]
        mod = propose_modification(contract["id"], delta_fixed_consideration_cents=200000)
        validate_success(api.approve_modification(mod["id"], manager_headers))
        # 25000 + 70000 already posted + 25000 + 70000 catch-up = 190000.
        assert get_period(period["id"])["recognized_total_cents"] == 190000
        contract_after = get_contract(contract["id"])
        assert contract_after["recognized_to_date_cents"] == 190000
        # Nothing billed: the whole recognized amount sits in the contract asset.
        assert contract_after["contract_asset_balance_cents"] == 190000
        assert contract_after["deferred_revenue_balance_cents"] == 0


class TestProspectiveModification:
    def _setup(self, api, accountant_headers):
        setup = setup_active_contract_with_pobs(
            [
                {"product_code": "ICA", "ssp_cents": 100000,
                 "pob": {"pob_ref": "P1", "recognition_pattern": "OVER_TIME_INPUT_COST",
                         "estimated_total_cost_cents": 40000}},
                {"product_code": "PITA", "ssp_cents": 100000,
                 "pob": {"pob_ref": "P2", "recognition_pattern": "POINT_IN_TIME"}},
            ],
            fixed=100000,
        )
        pob1, pob2 = setup["pobs"]
        # POB1 IN_PROGRESS: 20000/40000 = 50% of 50000 -> recognized 25000.
        validate_success(api.create_cost_entry(
            pob1["id"], {"amount_cents": 20000, "incurred_date": "2026-06-10"},
            accountant_headers,
        ), 201)
        assert get_pob(pob1["id"])["status"] == "IN_PROGRESS"
        assert get_pob(pob2["id"])["status"] == "PENDING"
        return setup

    def test_delta_allocated_to_pending_pobs_only(self, api, accountant_headers, manager_headers):
        """PRD §3.8: "only the delta is allocated, and only across `PENDING`
        obligations, pro-rata by their pinned `ssp_cents` — each share rounded
        half up to whole cents in `created_at` ascending order, the residual
        going to the `PENDING` obligation with the greatest `ssp_cents` (ties by
        earliest `created_at`). The shares are added onto the obligations'
        existing allocated amounts; amounts already recognized are untouched,
        and no catch-up entries are posted."

        Design: Corner/calculations/prospective_modification_allocates_delta_to_pending_pobs
        """
        setup = self._setup(api, accountant_headers)
        contract = setup["contract"]
        pob1, pob2 = setup["pobs"]
        mod = propose_modification(contract["id"], mod_type="PROSPECTIVE",
                                   delta_fixed_consideration_cents=40000)
        validate_success(api.approve_modification(mod["id"], manager_headers))
        p1 = get_pob(pob1["id"])
        assert p1["allocated_amount_cents"] == 50000, "IN_PROGRESS obligation untouched"
        assert p1["recognized_revenue_cents"] == 25000
        # Sole PENDING obligation receives the entire 40000 delta.
        assert get_pob(pob2["id"])["allocated_amount_cents"] == 90000

    def test_no_catchup_entries_and_totals(self, api, accountant_headers, manager_headers):
        """PRD §3.8: "The delta is applied to `fixed_consideration_cents` and
        the transaction price recomputed exactly as above, but the distribution
        is narrower: only the delta is allocated, and only across `PENDING`
        obligations, pro-rata by their pinned `ssp_cents` — each share rounded
        half up to whole cents in `created_at` ascending order, the residual
        going to the `PENDING` obligation with the greatest `ssp_cents` (ties by
        earliest `created_at`). The shares are added onto the obligations'
        existing allocated amounts; amounts already recognized are untouched,
        and no catch-up entries are posted."

        Design: Corner/calculations/prospective_modification_allocates_delta_to_pending_pobs
        """
        setup = self._setup(api, accountant_headers)
        contract = setup["contract"]
        mod = propose_modification(contract["id"], mod_type="PROSPECTIVE",
                                   delta_fixed_consideration_cents=40000)
        validate_success(api.approve_modification(mod["id"], manager_headers))
        after = get_contract(contract["id"])
        assert after["transaction_price_cents"] == 140000
        assert after["allocated_total_cents"] == 140000
        catchups = validate_paginated(api.list_revenue_entries(
            accountant_headers,
            params={"contract_id": contract["id"], "entry_type": "CATCH_UP_ADJUSTMENT"},
        ))[0]
        assert catchups == [], "PROSPECTIVE approvals post no catch-up entries"

    def test_no_pending_pob_rejected(self, api, accountant_headers, manager_headers):
        """PRD §3.8: "For `PROSPECTIVE`, at least one obligation must still be
        `PENDING` to receive the delta, failing otherwise with
        `ERR_NO_PENDING_POB` (HTTP 422)."

        Design: Corner/calculations/prospective_modification_without_pending_pob_rejected
        """
        setup = setup_active_contract_with_pob(
            product_code="ICA",
            pob_overrides={"recognition_pattern": "OVER_TIME_INPUT_COST",
                           "estimated_total_cost_cents": 40000},
        )
        pob = setup["pob"]
        validate_success(api.create_cost_entry(
            pob["id"], {"amount_cents": 20000, "incurred_date": "2026-06-10"},
            accountant_headers,
        ), 201)
        assert get_pob(pob["id"])["status"] == "IN_PROGRESS"
        mod = propose_modification(setup["contract"]["id"], mod_type="PROSPECTIVE",
                                   delta_fixed_consideration_cents=10000)
        resp = api.approve_modification(mod["id"], manager_headers)
        validate_error(resp, ApiErrorId.ERR_NO_PENDING_POB, 422)

    def test_rejected_prospective_approval_mutates_nothing(self, api, accountant_headers, manager_headers):
        """PRD §3.8: "For `PROSPECTIVE`, at least one obligation must still be
        `PENDING` to receive the delta, failing otherwise with
        `ERR_NO_PENDING_POB` (HTTP 422)."

        Design: Corner/calculations/prospective_modification_without_pending_pob_rejected
        """
        setup = setup_active_contract_with_pob(
            product_code="ICA",
            pob_overrides={"recognition_pattern": "OVER_TIME_INPUT_COST",
                           "estimated_total_cost_cents": 40000},
        )
        validate_success(api.create_cost_entry(
            setup["pob"]["id"], {"amount_cents": 20000, "incurred_date": "2026-06-10"},
            accountant_headers,
        ), 201)
        mod = propose_modification(setup["contract"]["id"], mod_type="PROSPECTIVE",
                                   delta_fixed_consideration_cents=10000)
        validate_error(api.approve_modification(mod["id"], manager_headers),
                       ApiErrorId.ERR_NO_PENDING_POB, 422)
        assert get_contract(setup["contract"]["id"])["fixed_consideration_cents"] == 100000
        mods = validate_paginated(
            api.list_modifications(setup["contract"]["id"], accountant_headers))[0]
        assert mods[0]["status"] == "PROPOSED"


class TestSeparateContractModification:
    def _setup(self, api):
        setup = setup_active_contract_with_pob()
        mod = propose_modification(
            setup["contract"]["id"], mod_type="SEPARATE_CONTRACT",
            delta_fixed_consideration_cents=80000, effective_date="2026-06-20",
        )
        return setup, mod

    def test_approval_spawns_new_draft_contract(self, api, manager_headers):
        """PRD §3.8: "For `SEPARATE_CONTRACT`, the original contract is left
        unchanged. Instead, approval creates a new contract in `DRAFT` for the
        same `customer_id`, with `signed_date` equal to the modification's
        `effective_date`, `fixed_consideration_cents` equal to the delta, and
        `risk_tier` copied from the original; the modification's
        `spawned_contract_id` is set to the new contract."

        Design: Corner/calculations/separate_contract_modification_spawns_new_draft
        """
        setup, mod = self._setup(None)
        approved = validate_success(api.approve_modification(mod["id"], manager_headers))
        assert approved["status"] == "APPROVED"
        spawned_id = approved["spawned_contract_id"]
        assert spawned_id, "spawned_contract_id must be set"
        spawned = get_contract(spawned_id)
        assert spawned["status"] == "DRAFT"
        assert spawned["fixed_consideration_cents"] == 80000
        assert spawned["signed_date"] == "2026-06-20"
        assert spawned["customer_id"] == setup["customer"]["id"]

    def test_original_contract_unchanged(self, api, manager_headers):
        """PRD §3.8: "For `SEPARATE_CONTRACT`, the original contract is left
        unchanged."

        Design: Corner/calculations/separate_contract_modification_spawns_new_draft
        """
        setup, mod = self._setup(None)
        validate_success(api.approve_modification(mod["id"], manager_headers))
        original = get_contract(setup["contract"]["id"])
        assert original["fixed_consideration_cents"] == 100000
        assert original["transaction_price_cents"] == 100000


class TestOverRecognitionGuard:
    def _setup(self, api, accountant_headers):
        setup = setup_active_contract_with_pob(
            pob_overrides={"recognition_pattern": "OVER_TIME_INPUT_COST",
                           "estimated_total_cost_cents": 40000},
        )
        validate_success(api.create_cost_entry(
            setup["pob"]["id"], {"amount_cents": 20000, "incurred_date": "2026-06-10"},
            accountant_headers,
        ), 201)
        assert get_pob(setup["pob"]["id"])["recognized_revenue_cents"] == 50000
        return setup

    def test_downward_modification_rejected(self, api, accountant_headers, manager_headers):
        """PRD §3.8: "Third, the over-recognition guard: if any obligation would
        land with `allocated_amount_cents` below its `recognized_revenue_cents`,
        the entire approval is rejected with `ERR_OVER_RECOGNITION` and no field
        is mutated."

        Design: Corner/errors/over_recognition_guard_rejects_downward_modification
        """
        setup = self._setup(api, accountant_headers)
        # -90000 would reallocate the single POB to 10000 < recognized 50000.
        mod = propose_modification(setup["contract"]["id"],
                                   delta_fixed_consideration_cents=-90000)
        resp = api.approve_modification(mod["id"], manager_headers)
        validate_error(resp, ApiErrorId.ERR_OVER_RECOGNITION, 422)

    def test_guard_rejection_is_atomic(self, api, accountant_headers, manager_headers):
        """PRD §3.8: "the entire approval is rejected with
        `ERR_OVER_RECOGNITION` and no field is mutated."

        Design: Corner/errors/over_recognition_guard_rejects_downward_modification
        """
        setup = self._setup(api, accountant_headers)
        mod = propose_modification(setup["contract"]["id"],
                                   delta_fixed_consideration_cents=-90000)
        validate_error(api.approve_modification(mod["id"], manager_headers),
                       ApiErrorId.ERR_OVER_RECOGNITION, 422)
        pob_after = get_pob(setup["pob"]["id"])
        assert pob_after["allocated_amount_cents"] == 100000
        assert pob_after["recognized_revenue_cents"] == 50000
        assert get_contract(setup["contract"]["id"])["fixed_consideration_cents"] == 100000
        mods = validate_paginated(
            api.list_modifications(setup["contract"]["id"], accountant_headers))[0]
        assert mods[0]["status"] == "PROPOSED"


class TestApprovalPriority:
    def test_state_gate_beats_fiscal_guard(self, api, accountant_headers, manager_headers):
        """PRD §2.8: "Every request passes through a fixed, tiered validation
        pipeline, and the first failing tier determines the error returned — a
        request that violates rules from several tiers always surfaces the
        earliest tier's error, never a later one's."
        (Tier 5 state validity, `ERR_CONTRACT_NOT_ACTIVE`, precedes tier 10
        fiscal caps, `ERR_OVER_RECOGNITION`.)

        Design: Difficulty/priority_pair_validation_conflict/conflict_state_vs_fiscal_on_modification_approve
        """
        setup = setup_active_contract_with_pob(
            pob_overrides={"recognition_pattern": "OVER_TIME_INPUT_COST",
                           "estimated_total_cost_cents": 40000},
        )
        contract, pob = setup["contract"], setup["pob"]
        validate_success(api.create_cost_entry(
            pob["id"], {"amount_cents": 20000, "incurred_date": "2026-06-10"},
            accountant_headers,
        ), 201)
        # Would breach the fiscal guard (10000 < 50000) if it were reached.
        mod = propose_modification(contract["id"], delta_fixed_consideration_cents=-90000)
        # The state gate is violated too: the contract is ON_HOLD.
        validate_success(api.hold_contract(contract["id"], manager_headers))
        resp = api.approve_modification(mod["id"], manager_headers)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE, 409)

    def test_state_rejection_leaves_modification_proposed(self, api, accountant_headers, manager_headers):
        """PRD §2.8: "a request that violates rules from several tiers always
        surfaces the earliest tier's error, never a later one's."
        PRD §3.4: "A `RevenueManager` may place an `ACTIVE` contract `ON_HOLD` —
        which blocks recognition, cost, invoice, and modification operations,
        each failing with `ERR_CONTRACT_NOT_ACTIVE` (HTTP 409) while the hold
        lasts".

        Design: Difficulty/priority_pair_validation_conflict/conflict_state_vs_fiscal_on_modification_approve
        """
        setup = setup_active_contract_with_pob(
            pob_overrides={"recognition_pattern": "OVER_TIME_INPUT_COST",
                           "estimated_total_cost_cents": 40000},
        )
        contract, pob = setup["contract"], setup["pob"]
        validate_success(api.create_cost_entry(
            pob["id"], {"amount_cents": 20000, "incurred_date": "2026-06-10"},
            accountant_headers,
        ), 201)
        mod = propose_modification(contract["id"], delta_fixed_consideration_cents=-90000)
        validate_success(api.hold_contract(contract["id"], manager_headers))
        validate_error(api.approve_modification(mod["id"], manager_headers),
                       ApiErrorId.ERR_CONTRACT_NOT_ACTIVE, 409)
        mods = validate_paginated(api.list_modifications(contract["id"], accountant_headers))[0]
        assert mods[0]["status"] == "PROPOSED"
        # The fiscal guard never ran: no field moved.
        assert get_contract(contract["id"])["fixed_consideration_cents"] == 100000

    def _setup_sod_and_closed(self, api, controller_headers):
        """CATCH_UP +60000 proposed by user-7; June period then CLOSED."""
        setup = setup_active_contract_with_pob(
            pob_overrides={"recognition_pattern": "OVER_TIME_INPUT_COST",
                           "estimated_total_cost_cents": 40000},
        )
        contract, pob, period = setup["contract"], setup["pob"], setup["period"]
        acct7 = make_accountant_headers("user-7")
        validate_success(api.create_cost_entry(
            pob["id"], {"amount_cents": 20000, "incurred_date": "2026-06-10"}, acct7,
        ), 201)
        mod = validate_success(api.create_modification(
            contract["id"],
            create_modification_payload(get_contract_version(contract["id"]),
                                        delta_fixed_consideration_cents=60000),
            acct7,
        ), 201)
        validate_success(api.close_accounting_period(period["id"], controller_headers))
        return setup, mod

    def test_sod_beats_temporal_gate(self, api, controller_headers):
        """PRD §2.8: "a clause-review or duty-segregation gate (tier 6) is
        reported before a period-window problem (tier 7)".

        Design: Difficulty/priority_pair_validation_conflict/conflict_safety_vs_temporal_on_modification_approve
        """
        _, mod = self._setup_sod_and_closed(api, controller_headers)
        # Same operator proposes (as accountant) and approves (as manager):
        # SoD (tier 6) fires even though the clock date is in a CLOSED period.
        resp = api.approve_modification(mod["id"], make_manager_headers("user-7"))
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION, 409)

    def test_sod_rejection_leaves_modification_proposed(self, api, controller_headers):
        """PRD §2.8: "a clause-review or duty-segregation gate (tier 6) is
        reported before a period-window problem (tier 7)".
        PRD §2.10: "A contract modification may not be approved by the operator
        who proposed it — the approver's `X-User-ID` must differ from the
        modification's `proposed_by_user_id`."

        Design: Difficulty/priority_pair_validation_conflict/conflict_safety_vs_temporal_on_modification_approve
        """
        setup, mod = self._setup_sod_and_closed(api, controller_headers)
        validate_error(api.approve_modification(mod["id"], make_manager_headers("user-7")),
                       ApiErrorId.ERR_SOD_VIOLATION, 409)
        mods = validate_paginated(api.list_modifications(
            setup["contract"]["id"], make_accountant_headers("acct-1")))[0]
        assert mods[0]["status"] == "PROPOSED"

    def test_clean_approver_hits_temporal_gate(self, api, accountant_headers, manager_headers):
        """PRD §3.8: "For `CUMULATIVE_CATCH_UP`, the period containing the
        current clock date must be `OPEN` or `REOPENED` (`ERR_PERIOD_CLOSED`)".

        Design: Corner/validations/catchup_approve_in_closed_period_returns_period_closed
        """
        setup = setup_active_contract_with_pob(
            pob_overrides={"recognition_pattern": "OVER_TIME_INPUT_COST",
                           "estimated_total_cost_cents": 40000},
        )
        contract, pob, period = setup["contract"], setup["pob"], setup["period"]
        validate_success(api.create_cost_entry(
            pob["id"], {"amount_cents": 20000, "incurred_date": "2026-06-10"},
            accountant_headers,
        ), 201)
        mod = propose_modification(contract["id"], delta_fixed_consideration_cents=60000)
        validate_success(api.close_accounting_period(period["id"], TEST_USERS["controller_headers"]))
        resp = api.approve_modification(mod["id"], make_manager_headers("mgr-9"))
        validate_error(resp, ApiErrorId.ERR_PERIOD_CLOSED, 409)

    def test_temporal_rejection_posts_no_catchup(self, api, accountant_headers, controller_headers):
        """PRD §3.8: "For `CUMULATIVE_CATCH_UP`, the period containing the
        current clock date must be `OPEN` or `REOPENED` (`ERR_PERIOD_CLOSED`)".

        Design: Corner/validations/catchup_approve_in_closed_period_returns_period_closed
        """
        setup = setup_active_contract_with_pob(
            pob_overrides={"recognition_pattern": "OVER_TIME_INPUT_COST",
                           "estimated_total_cost_cents": 40000},
        )
        contract, pob, period = setup["contract"], setup["pob"], setup["period"]
        validate_success(api.create_cost_entry(
            pob["id"], {"amount_cents": 20000, "incurred_date": "2026-06-10"},
            accountant_headers,
        ), 201)
        mod = propose_modification(contract["id"], delta_fixed_consideration_cents=60000)
        validate_success(api.close_accounting_period(period["id"], controller_headers))
        validate_error(api.approve_modification(mod["id"], make_manager_headers("mgr-9")),
                       ApiErrorId.ERR_PERIOD_CLOSED, 409)
        catchups = validate_paginated(api.list_revenue_entries(
            accountant_headers,
            params={"contract_id": contract["id"], "entry_type": "CATCH_UP_ADJUSTMENT"},
        ))[0]
        assert catchups == [], "no catch-up entries may be posted into a closed period"
        mods = validate_paginated(api.list_modifications(contract["id"], accountant_headers))[0]
        assert mods[0]["status"] == "PROPOSED"
