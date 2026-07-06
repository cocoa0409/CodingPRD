"""Renewal escalation variants, renewal side effects, OCC on contract, upsell."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_renewal_cycle_payload, create_upsell_payload, create_contract_payload,
    setup_servicing_contract, setup_offered_renewal, setup_sent_proposal,
    make_account_manager_headers,
    SINGLE_LIGHT_AREA, TEST_USERS,
)
from test_helpers.fixtures import AM_USER_ID

_SALES = TEST_USERS["sales_rep_headers"]
_AM = make_account_manager_headers(AM_USER_ID)

# Single LIGHT 4000@1/wk yields a SERVICING contract monthly_value of 29976.
SERVICING_VALUE = 29976


class TestRenewalEscalationVariants:
    """Difficulty rule: dual_variant_calc / renewal_escalation_cpi_vs_flat."""

    def test_cpi_escalation_multiplies_base(self, api):
        """PRD §3.10: "Under the CPI method the proposed price is that base multiplied by
        the quantity one plus 0.032 (a 3.2 percent consumer-price escalation), rounded
        half up to whole cents."
        PRD §3.10: "The escalation starts from the contract's current monthly_value_cents."

        Design: Difficulty/dual_variant_calc/renewal_escalation_cpi_vs_flat
        """
        acct, rfp, ctr, plan = setup_servicing_contract(areas=SINGLE_LIGHT_AREA, legal_name="CPI Co")
        assert ctr["monthly_value_cents"] == SERVICING_VALUE
        rc = validate_success(api.create_renewal_cycle(
            acct["id"], ctr["id"], create_renewal_cycle_payload("CPI"), _AM), 201)
        # round_half_up(29976 * 1.032) = round_half_up(30935.232) = 30935
        assert rc["proposed_monthly_cents"] == 30935

    def test_flat_escalation_adds_fixed_amount(self, api):
        """PRD §3.10: "Under the FLAT method the proposed price is the base plus a fixed
        increase of 15000 cents. The two methods diverge for the same contract value."

        Design: Difficulty/dual_variant_calc/renewal_escalation_cpi_vs_flat
        """
        acct, rfp, ctr, plan = setup_servicing_contract(areas=SINGLE_LIGHT_AREA, legal_name="FLAT Co")
        assert ctr["monthly_value_cents"] == SERVICING_VALUE
        rc = validate_success(api.create_renewal_cycle(
            acct["id"], ctr["id"], create_renewal_cycle_payload("FLAT"), _AM), 201)
        # 29976 + 15000 = 44976, distinct from the CPI result.
        assert rc["proposed_monthly_cents"] == SERVICING_VALUE + 15000


class TestRenewalCornerClaims:
    """Corner sections: state_machines / validations / cross_cutting_complexity_layers."""

    def test_accept_flat_renewal_bumps_contract_value(self, api):
        """PRD §3.10: "Acceptance sets the contract's monthly_value_cents to the cycle's
        proposed_monthly_cents and credits the account's health_score by the renewal
        bonus, capped at 100."

        Design: Corner/state_machines/renewal_accept_bumps_contract_value_flat
        """
        acct, ctr, rc, ctr_v = setup_offered_renewal(
            escalation_method="FLAT", areas=SINGLE_LIGHT_AREA, legal_name="RenSE Co")
        assert rc["proposed_monthly_cents"] == 44976
        accepted = validate_success(api.accept_renewal(
            acct["id"], rc["id"], {"expected_contract_version": ctr_v}, _AM), 200)
        assert accepted["status"] == "RENEWED"
        ctr_after = validate_success(api.get_contract(acct["id"], ctr["id"], _AM), 200)
        assert ctr_after["monthly_value_cents"] == 44976

    def test_renewed_cycle_cannot_lapse(self, api):
        """PRD §3.10: "Lapsing an offered renewal moves it from OFFERED to LAPSED (must
        be OFFERED, otherwise ERR_INVALID_STATE)".

        Design: Corner/state_machines/terminal_renewed_cycle_cannot_lapse
        """
        acct, ctr, rc, ctr_v = setup_offered_renewal(
            escalation_method="FLAT", areas=SINGLE_LIGHT_AREA, legal_name="RenTerm Co")
        validate_success(api.accept_renewal(
            acct["id"], rc["id"], {"expected_contract_version": ctr_v}, _AM), 200)
        res = api.lapse_renewal(acct["id"], rc["id"], _AM)
        validate_error(res, "ERR_INVALID_STATE")

    def test_renewal_on_non_servicing_contract_rejected(self, api):
        """PRD §3.10: "the parent contract must be SERVICING, otherwise
        ERR_CONTRACT_NOT_SERVICING."

        Design: Corner/validations/renewal_on_non_servicing_contract_returns_error
        """
        # A DRAFT (never signed) contract is not SERVICING.
        acct, rfp, bid, prop = setup_sent_proposal(areas=SINGLE_LIGHT_AREA, legal_name="NSvc Co")
        validate_success(api.accept_proposal(acct["id"], rfp["id"], prop["id"], _SALES), 200)
        ctr = validate_success(api.create_contract(
            acct["id"], create_contract_payload(prop["id"]), _SALES), 201)
        res = api.create_renewal_cycle(
            acct["id"], ctr["id"], create_renewal_cycle_payload("CPI"), _AM)
        validate_error(res, "ERR_CONTRACT_NOT_SERVICING")

    def test_stale_contract_version_on_renewal_accept_rejected(self, api):
        """PRD §2.9: "If another renewal, billing action, or upsell has already advanced
        the contract's version since the client last read it, the accept is rejected
        with ERR_STALE_VERSION (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_contract_version_on_renewal_accept
        """
        acct, ctr, rc, ctr_v0 = setup_offered_renewal(
            escalation_method="FLAT", areas=SINGLE_LIGHT_AREA, legal_name="OCC2 Co")
        # An upsell advances the contract version, making ctr_v0 stale.
        validate_success(api.upsell_contract(
            acct["id"], ctr["id"],
            create_upsell_payload(monthly_addon_cents=5000, expected_contract_version=ctr_v0,
                                  upsell_type="WINDOW"), _AM), 200)
        res = api.accept_renewal(
            acct["id"], rc["id"], {"expected_contract_version": ctr_v0}, _AM)
        validate_error(res, "ERR_STALE_VERSION")
        rc_after = validate_success(api.get_renewal_cycle(acct["id"], rc["id"], _AM), 200)
        assert rc_after["status"] == "OFFERED"

    def test_upsell_raises_contract_value(self, api):
        """PRD §3.10: "On success the contract's monthly_value_cents increases by
        monthly_addon_cents, the contract's version increments by one, and the account's
        health_score is credited by the upsell bonus, capped at 100."

        Design: Corner/cross_cutting_complexity_layers/upsell_raises_contract_value
        """
        acct, rfp, ctr, plan = setup_servicing_contract(areas=SINGLE_LIGHT_AREA, legal_name="Up Co")
        assert ctr["monthly_value_cents"] == SERVICING_VALUE
        ctr_v = validate_success(api.get_contract(acct["id"], ctr["id"], _AM), 200)["version"]
        upsold = validate_success(api.upsell_contract(
            acct["id"], ctr["id"],
            create_upsell_payload(monthly_addon_cents=5000, expected_contract_version=ctr_v,
                                  upsell_type="FLOOR"), _AM), 200)
        assert upsold["monthly_value_cents"] == SERVICING_VALUE + 5000
