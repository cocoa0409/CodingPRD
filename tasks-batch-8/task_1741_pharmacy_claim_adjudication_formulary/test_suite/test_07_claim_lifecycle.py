"""Claim lifecycle: resubmit/reverse/reprocess state gates and the PAID-REVERSED-PAID cycle."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_adjudication_scenario,
    submit_claim, create_paid_claim, get_claim, get_member, get_pharmacy,
    get_only_rejected_claim,
)


def test_claim_reverse_from_rejected_rejected(api):
    """PRD §3.7: "Reversal is performed by the owning pharmacy's pharmacist — any other
    pharmacy is `ERR_PHARMACY_MISMATCH` — requires the claim to stand in `PAID`
    (otherwise `ERR_CLAIM_NOT_PAID`) and the pharmacy to be `ACTIVE` (otherwise
    `ERR_PHARMACY_SUSPENDED`), and carries a free-text `reversal_reason`."

    Design: Corner/state_machines/claim_reverse_from_rejected_rejected
    """
    scenario = make_adjudication_scenario(
        drug_overrides={"ndc": "00000-9005", "name": "Reverso", "unit_cost_cents": 100,
                        "max_daily_dose_units": 100},
        entry_overrides={"quantity_limit_per_fill": 90, "copay_flat_cents": 100},
    )
    member_id = scenario["member"]["id"]
    res = submit_claim(member_id, scenario["drug"]["id"], scenario["pharmacy"]["id"],
                       fill_date="2026-03-01", quantity=91, days_supply=30)
    validate_error(res, "ERR_QUANTITY_LIMIT_EXCEEDED", expected_status=422)
    rejected = get_only_rejected_claim(member_id)

    res = api.reverse_claim(rejected["id"], {"reversal_reason": "premature"},
                            scenario["pharmacist_headers"])
    validate_error(res, "ERR_CLAIM_NOT_PAID", expected_status=409)
    after = get_claim(rejected["id"], scenario["pharmacist_headers"])
    assert after["status"] == "REJECTED"
    assert after["reject_reasons"] == ["ERR_QUANTITY_LIMIT_EXCEEDED"]


def test_claim_resubmit_from_paid_rejected(api):
    """PRD §3.7: "Resubmission is the parallel corrective path from `REJECTED`, open
    only while the claim stands in `REJECTED` (otherwise `ERR_CLAIM_NOT_REJECTED`) and
    only to the owning, non-suspended pharmacy."

    Design: Corner/state_machines/claim_resubmit_from_paid_rejected
    """
    scenario = make_adjudication_scenario(
        drug_overrides={"ndc": "00000-9006", "name": "Submitra", "unit_cost_cents": 100,
                        "max_daily_dose_units": 100},
        entry_overrides={"quantity_limit_per_fill": 120, "copay_flat_cents": 100},
    )
    claim = create_paid_claim(scenario["member"]["id"], scenario["drug"]["id"],
                              scenario["pharmacy"]["id"], fill_date="2026-03-01",
                              quantity=100, days_supply=30)
    assert claim["plan_paid_cents"] == 9900

    res = api.resubmit_claim(claim["id"], {}, scenario["pharmacist_headers"])
    validate_error(res, "ERR_CLAIM_NOT_REJECTED", expected_status=409)
    after = get_claim(claim["id"], scenario["pharmacist_headers"])
    assert after["status"] == "PAID"
    assert after["plan_paid_cents"] == 9900
    assert after["resubmit_count"] == 0


def test_claim_reprocess_from_paid_rejected(api):
    """PRD §3.7: "The operation requires the claim to be `REVERSED` (otherwise
    `ERR_CLAIM_NOT_REVERSED`) and the pharmacy `ACTIVE`."

    Design: Corner/state_machines/claim_reprocess_from_paid_rejected
    """
    scenario = make_adjudication_scenario(
        drug_overrides={"ndc": "00000-9007", "name": "Reproses", "unit_cost_cents": 100,
                        "max_daily_dose_units": 100},
        entry_overrides={"quantity_limit_per_fill": 120, "copay_flat_cents": 100},
    )
    claim = create_paid_claim(scenario["member"]["id"], scenario["drug"]["id"],
                              scenario["pharmacy"]["id"], fill_date="2026-03-01")

    res = api.reprocess_claim(claim["id"], {"quantity": 5}, scenario["pharmacist_headers"])
    validate_error(res, "ERR_CLAIM_NOT_REVERSED", expected_status=409)
    after = get_claim(claim["id"], scenario["pharmacist_headers"])
    assert after["status"] == "PAID"
    assert after["quantity"] == 10


class TestPaidReversedRepaidCycle:
    def _cycle_scenario(self):
        scenario = make_adjudication_scenario(
            plan_overrides={"oop_max_cents": 1000000},
            drug_overrides={"ndc": "44444-0001", "name": "Sterodex",
                            "therapeutic_class": "STEROID", "unit_cost_cents": 10000,
                            "max_daily_dose_units": 100},
            entry_overrides={"tier": 3, "copay_flat_cents": 3000, "rebate_eligible": True},
        )
        claim = create_paid_claim(
            scenario["member"]["id"], scenario["drug"]["id"], scenario["pharmacy"]["id"],
            fill_date="2026-03-01", quantity=30, days_supply=30,
        )
        assert claim["allowed_cents"] == 300000
        assert claim["member_pays_cents"] == 3000
        assert claim["plan_paid_cents"] == 297000
        assert claim["rebate_tag"] == "REBATE_ELIGIBLE"
        return scenario, claim

    def test_reverse_paid_claim_compensates_and_voids_rebate(self, api, pbm_admin_headers):
        """PRD §3.7: "Reversal is exact compensation against the claim's stored
        financial fields, so accumulators and ledgers return to their pre-claim values"
        PRD §3.5: "When a previously eligible claim is reversed or clawed back by audit,
        its tag moves from `REBATE_ELIGIBLE` to `REBATE_VOID`; a tag of
        `REBATE_INELIGIBLE` is unchanged by those events."

        Design: Difficulty/non_linear_state_machine/claim_paid_reversed_repaid_cycle
        """
        scenario, claim = self._cycle_scenario()
        reversed_claim = validate_success(
            api.reverse_claim(claim["id"], {"reversal_reason": "dispensing error"},
                              scenario["pharmacist_headers"]),
            200,
        )
        assert reversed_claim["status"] == "REVERSED"
        assert reversed_claim["rebate_tag"] == "REBATE_VOID"
        member = get_member(scenario["member"]["id"], pbm_admin_headers)
        assert member["oop_paid_cents"] == 0
        pharmacy = get_pharmacy(scenario["pharmacy"]["id"])
        assert pharmacy["balance_cents"] == 0

    def test_reprocess_reversed_claim_repays_with_corrected_quantity(self, api, pbm_admin_headers):
        """PRD §3.7: "If every edit passes, the response is 200, all financial fields
        are recomputed from the corrected values, and the full posting cascade of §3.5
        applies exactly as on a fresh payment, returning the claim to `PAID`."
        PRD §3.5: "When a claim enters `PAID`, its `rebate_tag` is set to
        `REBATE_ELIGIBLE` if the governing formulary entry's `rebate_eligible` flag is
        true, and `REBATE_INELIGIBLE` otherwise."

        Design: Difficulty/non_linear_state_machine/claim_paid_reversed_repaid_cycle
        """
        scenario, claim = self._cycle_scenario()
        validate_success(
            api.reverse_claim(claim["id"], {"reversal_reason": "dispensing error"},
                              scenario["pharmacist_headers"]),
            200,
        )
        repaid = validate_success(
            api.reprocess_claim(claim["id"], {"quantity": 20}, scenario["pharmacist_headers"]),
            200,
        )
        assert repaid["status"] == "PAID"
        assert repaid["quantity"] == 20
        assert repaid["allowed_cents"] == 200000
        assert repaid["member_pays_cents"] == 3000
        assert repaid["plan_paid_cents"] == 197000
        assert repaid["rebate_tag"] == "REBATE_ELIGIBLE"
        member = get_member(scenario["member"]["id"], pbm_admin_headers)
        assert member["oop_paid_cents"] == 3000
        pharmacy = get_pharmacy(scenario["pharmacy"]["id"])
        assert pharmacy["balance_cents"] == 197000
