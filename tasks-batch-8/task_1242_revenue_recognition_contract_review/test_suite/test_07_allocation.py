"""SSP allocation waterfall at contract approval (PRD §3.4)."""
import pytest

from test_helpers import (
    ApiErrorId, validate_success, validate_error,
    create_customer, create_contract, create_ssp, add_pob,
    submit_contract, approve_contract, get_contract, get_pob,
)


class TestRoundingResidual:
    def _setup_three_pob_contract(self):
        """tx 1000000 over SSPs 100000/200000/333333 created PA, PB, PC in order."""
        create_ssp("PA", region="US", ssp_cents=100000)
        create_ssp("PB", region="US", ssp_cents=200000)
        create_ssp("PC", region="US", ssp_cents=333333)
        customer = create_customer(legal_name="Round Co", external_ref="RND-1")
        contract = create_contract(customer["id"], contract_ref="C-ALLOC",
                                   fixed_consideration_cents=1000000)
        pa = add_pob(contract["id"], pob_ref="PA", product_code="PA", region="US")
        pb = add_pob(contract["id"], pob_ref="PB", product_code="PB", region="US")
        pc = add_pob(contract["id"], pob_ref="PC", product_code="PC", region="US")
        submit_contract(contract["id"])
        return contract, pa, pb, pc

    def test_per_line_rounding_and_residual_landing(self, api, manager_headers):
        """PRD §3.4: "obligations are processed in `created_at` ascending order,
        and each line is rounded half up to whole cents before the next is
        considered. The residual — the transaction price minus the sum of the
        rounded lines — is added to the pool obligation with the greatest
        `ssp_cents`, with ties broken by the earliest `created_at`; resource ids
        never participate in ordering."

        Design: Difficulty/combinatorial_formula/ssp_allocation_rounding_residual
        """
        contract, pa, pb, pc = self._setup_three_pob_contract()
        validate_success(api.approve_contract(contract["id"], manager_headers))
        # raw: 157894.736..., 315789.473..., 526315.789...
        # rounded: 157895 + 315790 + 526316 = 1000001 -> residual -1 to greatest-SSP POB (PC).
        assert get_pob(pa["id"])["allocated_amount_cents"] == 157895
        assert get_pob(pb["id"])["allocated_amount_cents"] == 315790
        assert get_pob(pc["id"])["allocated_amount_cents"] == 526315

    def test_sum_invariant_and_contract_total(self, api, manager_headers):
        """PRD §3.4: "After the residual lands, the allocated lines sum exactly
        to the transaction price, and the contract's `allocated_total_cents` is
        set to `transaction_price_cents`."

        Design: Difficulty/combinatorial_formula/ssp_allocation_rounding_residual
        """
        contract, pa, pb, pc = self._setup_three_pob_contract()
        approved = validate_success(api.approve_contract(contract["id"], manager_headers))
        amounts = [get_pob(p["id"])["allocated_amount_cents"] for p in (pa, pb, pc)]
        assert sum(amounts) == 1000000
        assert approved["allocated_total_cents"] == 1000000
        assert approved["transaction_price_cents"] == 1000000

    def test_approval_pins_lines_and_bumps_version(self, api, manager_headers):
        """PRD §3.4: "Each obligation's `allocated_amount_cents` is written at
        this moment, and approval bumps the contract's `version`."

        Design: Difficulty/combinatorial_formula/ssp_allocation_rounding_residual
        """
        contract, pa, pb, pc = self._setup_three_pob_contract()
        before = get_contract(contract["id"])["version"]
        approved = validate_success(api.approve_contract(contract["id"], manager_headers))
        assert approved["version"] == before + 1
        assert get_pob(pa["id"])["allocated_amount_cents"] > 0
