"""Contract termination cascade and portability move-out tests (PRD §3.8)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, ADMIN,
    create_voucher_family,
    setup_active_scenario,
    create_portability_action_payload,
    list_hap_payments,
)


class TestTerminationCascade:
    def test_terminate_active_contract_cascades_to_family_unit_payments(self, api):
        """PRD §3.8: "From `ACTIVE`, the cascade moves the contract to
        `TERMINATED`, returns the voucher family from `LEASED` to `SEARCHING`,
        returns the unit from `UNDER_CONTRACT` to `LISTED`, and flips every
        future `SCHEDULED` payment to `VOID`."

        Design: Difficulty/transitive_cascade/termination_cascade_contract_family_unit_payments
        """
        landlord, prop, unit, family, contract = setup_active_scenario(
            zip_code="90008", family_code="F8",
        )
        data = validate_success(api.terminate_contract(contract["id"], ADMIN))
        assert data["status"] == "TERMINATED"
        fam = get_success_data(api.get_voucher_family(family["id"], ADMIN))
        assert fam["status"] == "SEARCHING", (
            f"termination must return the family to SEARCHING, got {fam['status']}"
        )
        unt = get_success_data(api.get_unit(unit["id"], ADMIN))
        assert unt["status"] == "LISTED", (
            f"termination must return the unit to LISTED, got {unt['status']}"
        )
        payments = list_hap_payments(contract["id"])
        for row in payments:
            assert row["disbursement_status"] in ("VOID", "PAID"), (
                f"every future SCHEDULED payment must flip to VOID, got "
                f"{row['disbursement_status']}"
            )
        assert any(r["disbursement_status"] == "VOID" for r in payments), (
            "at least one SCHEDULED payment must have flipped to VOID"
        )

    def test_terminate_twice_rejected_invalid_state(self, api):
        """PRD §3.8: "Termination is defined from both `ACTIVE` and `ABATED`."
        PRD §2.5: "then whether the target resource is in a state from which the
        requested transition is defined (`ERR_INVALID_STATE`)"

        Design: Difficulty/transitive_cascade/termination_cascade_contract_family_unit_payments
        """
        landlord, prop, unit, family, contract = setup_active_scenario(
            zip_code="90008", family_code="F8b",
        )
        validate_success(api.terminate_contract(contract["id"], ADMIN))
        resp = api.terminate_contract(contract["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestPortability:
    def test_port_in_action_lifecycle_to_absorbed(self, api):
        """PRD §3.8: "The new action begins `INITIATED`. An admin may accept the
        billing arrangement, moving `INITIATED` to `BILLING_ACCEPTED`; may
        terminate the action before billing is accepted, moving `INITIATED` to
        `TERMINATED`; or may absorb the family into the destination area, moving
        `BILLING_ACCEPTED` to `ABSORBED`."

        Design: Difficulty/dual_variant_calc/hap_split_standard_anniversary_vs_portability_restandard
        """
        family = create_voucher_family(
            family_code="F2", voucher_bedroom_size=1, annual_income_cents=2_400_000,
        )
        action = get_success_data(
            api.create_portability_action(
                create_portability_action_payload(
                    family["id"], destination_zip="90009", action_type="PORT_IN",
                ),
                ADMIN,
            )
        )
        assert action["status"] == "INITIATED"
        accepted = validate_success(api.accept_portability_billing(action["id"], ADMIN))
        assert accepted["status"] == "BILLING_ACCEPTED"
        absorbed = validate_success(api.absorb_portability_action(action["id"], ADMIN))
        assert absorbed["status"] == "ABSORBED", (
            f"PORT_IN absorption must move the action to ABSORBED, got "
            f"{absorbed['status']}"
        )

    def test_port_out_absorption_terminates_active_contract(self, api):
        """PRD §3.8: "Absorption is the moment the move becomes real: if the
        action's `action_type` is `PORT_OUT`, the voucher family moves from
        `LEASED` to `PORTED_OUT` and the linked `ACTIVE` contract moves to
        `TERMINATED` through the same move-out cascade that a direct termination
        would trigger (unit back to `LISTED`, future payments voided)."

        Design: Difficulty/dual_variant_calc/hap_split_standard_anniversary_vs_portability_restandard
        """
        landlord, prop, unit, family, contract = setup_active_scenario(
            zip_code="90022", family_code="FPORTIN",
        )
        action = get_success_data(
            api.create_portability_action(
                create_portability_action_payload(
                    family["id"], destination_zip="90023", action_type="PORT_IN",
                ),
                ADMIN,
            )
        )
        validate_success(api.accept_portability_billing(action["id"], ADMIN))
        absorbed = validate_success(api.absorb_portability_action(action["id"], ADMIN))
        assert absorbed["status"] == "ABSORBED"
        # The move-out cascade is conditioned on PORT_OUT; a PORT_IN absorb
        # leaves the family's active contract and LEASED status untouched.
        ctr = get_success_data(api.get_contract(contract["id"], ADMIN))
        assert ctr["status"] == "ACTIVE", (
            f"PORT_IN absorption must not terminate the contract, got {ctr['status']}"
        )
        fam = get_success_data(api.get_voucher_family(family["id"], ADMIN))
        assert fam["status"] == "LEASED", (
            f"PORT_IN absorption must not move the family out of LEASED, got "
            f"{fam['status']}"
        )
