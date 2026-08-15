"""RBAC denial and ownership-chain tests (PRD §2.1, §2.6, §4)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, ADMIN, INSPECTOR,
    create_landlord, create_property, create_unit, create_voucher_family,
    create_payment_standard,
    setup_priced_unit, setup_active_scenario, setup_failed_inspection,
    create_draft_contract,
    list_hap_payments,
    make_landlord_headers,
)


class TestLandlordCannotDisburse:
    def test_landlord_disburse_rejected_unauthorized(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted on
        the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: the disburse endpoint's authorized role is
        `HousingAuthorityAdmin` only.

        Design: Corner/rbac/landlord_cannot_disburse_hap_payment
        """
        landlord, prop, unit, family, contract = setup_active_scenario(
            zip_code="90311", family_code="CF14",
        )
        payments = list_hap_payments(contract["id"])
        assert payments, "Setup: activation must schedule one payment row"
        resp = api.disburse_hap_payment(
            payments[0]["id"], make_landlord_headers(landlord["id"])
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


class TestOwnershipChain:
    def test_other_landlord_cannot_mark_item_repaired(self, api):
        """PRD §2.6: "If the acting landlord's `id` does not equal the owning
        `landlord_id`, the request is rejected with `ERR_NOT_OWNER` (HTTP 403).
        This ownership check applies to: creating a unit within a property,
        creating a contract, submitting a contract, withdrawing a contract,
        delisting a unit, marking a repair item repaired, requesting a
        reinspection, creating a rent-increase request, and withdrawing a
        rent-increase request."

        Design: Corner/rbac/landlord_cannot_mark_other_landlords_item_repaired
        """
        owner, prop, unit, family, contract = setup_active_scenario(
            zip_code="90312", family_code="CFA",
        )
        inspection, item = setup_failed_inspection(contract, owner)
        intruder = create_landlord(legal_name="Owner B", tax_id="CTB")
        resp = api.mark_repair_item_repaired(
            item["id"], make_landlord_headers(intruder["id"])
        )
        validate_error(resp, ApiErrorId.ERR_NOT_OWNER)

    def test_other_landlord_cannot_submit_contract(self, api):
        """PRD §2.6: "If the acting landlord's `id` does not equal the owning
        `landlord_id`, the request is rejected with `ERR_NOT_OWNER` (HTTP 403).
        This ownership check applies to: creating a unit within a property,
        creating a contract, submitting a contract, withdrawing a contract,
        delisting a unit, marking a repair item repaired, requesting a
        reinspection, creating a rent-increase request, and withdrawing a
        rent-increase request."

        Design: Corner/rbac/landlord_cannot_mark_other_landlords_item_repaired
        """
        owner, prop, unit, family = setup_priced_unit(
            zip_code="90312", bedroom_count=1, standard_cents=150_000,
            family_income_cents=2_400_000, family_code="CFB",
        )
        contract = create_draft_contract(unit, family, owner)
        intruder = create_landlord(legal_name="Owner C", tax_id="CTC")
        resp = api.submit_contract(
            contract["id"], make_landlord_headers(intruder["id"])
        )
        validate_error(resp, ApiErrorId.ERR_NOT_OWNER)
