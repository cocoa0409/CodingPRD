"""Parent-child reverse reachability and list filtering (PRD §3.1, §3.3)."""
import pytest

from test_helpers import (
    validate_success, validate_paginated,
    create_customer, create_contract, create_ssp, add_pob,
    assert_pob,
)


class TestReverseReachability:
    def _setup(self):
        create_ssp("PA", region="US", ssp_cents=100000)
        create_ssp("PB", region="US", ssp_cents=100000)
        customer = create_customer(legal_name="FK Co", external_ref="FK-1")
        contract = create_contract(customer["id"], contract_ref="C-FK",
                                   fixed_consideration_cents=200000)
        pa = add_pob(contract["id"], pob_ref="PA", product_code="PA")
        pb = add_pob(contract["id"], pob_ref="PB", product_code="PB")
        return customer, contract, pa, pb

    def test_pobs_subresource_lists_children(self, api, accountant_headers):
        """PRD §3.3: "its `contract_id` ties it to the owning contract."
        PRD §4: `GET /revrec/contracts/{id}/pobs` — "List performance
        obligations of a contract".

        Design: Corner/entities/fk_reverse_reachability_lists_children
        """
        _, contract, pa, pb = self._setup()
        pobs, meta = validate_paginated(api.list_pobs(contract["id"], accountant_headers))
        assert meta["total_count"] == 2
        assert {p["id"] for p in pobs} == {pa["id"], pb["id"]}
        for pob in pobs:
            assert_pob(pob)
            assert pob["contract_id"] == contract["id"]

    def test_contracts_filter_by_customer(self, api, accountant_headers):
        """PRD §3.1: "The contract list supports optional `customer_id`,
        `status`, and `combined_into_contract_id` filters."

        Design: Corner/entities/fk_reverse_reachability_lists_children
        """
        customer, contract, _, _ = self._setup()
        # A second customer's contracts must not leak into the filtered list.
        other = create_customer(legal_name="Other Co", external_ref="OTHER-1")
        create_contract(other["id"], contract_ref="C-OTHER")
        listed, meta = validate_paginated(api.list_contracts(
            accountant_headers, params={"customer_id": customer["id"]}
        ))
        assert meta["total_count"] == 1
        assert [c["id"] for c in listed] == [contract["id"]]

    def test_contracts_filter_by_status(self, api, accountant_headers):
        """PRD §3.1: "The contract list supports optional `customer_id`,
        `status`, and `combined_into_contract_id` filters."

        Design: Corner/entities/fk_reverse_reachability_lists_children
        """
        _, contract, _, _ = self._setup()
        listed, meta = validate_paginated(api.list_contracts(
            accountant_headers, params={"status": "DRAFT"}
        ))
        assert meta["total_count"] >= 1
        assert all(c["status"] == "DRAFT" for c in listed)
        assert any(c["id"] == contract["id"] for c in listed)
