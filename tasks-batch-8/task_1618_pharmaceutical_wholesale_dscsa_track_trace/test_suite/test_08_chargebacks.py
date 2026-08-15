"""340B chargeback reconciliation: gross vs net computation bases, the claim
state machine (validate/settle/deny), and the referential gates."""
from test_helpers import (
    ApiErrorId,
    ClaimStatus,
    create_customer,
    create_order,
    get_claim,
    set_clock,
    setup_340b_allocated_order,
    submit_claim,
    validate_error,
    validate_success,
)

CLAIM_VALIDATION_RULE = (
    "Validation by a `ContractAdministrator` requires the claim to be "
    "`SUBMITTED` (`ERR_CLAIM_NOT_SUBMITTED`), then re-verifies the 340B flag, "
    "then recomputes `computed_amount_cents` and requires it to equal "
    "`claimed_amount_cents` exactly (`ERR_CHARGEBACK_AMOUNT_MISMATCH`, HTTP "
    "422); success moves the claim to `VALIDATED` and increments its `version`."
)


class TestChargebackBases:
    """Same claimed input, two bases: full allocation captures the whole
    WAC-to-contract delta; shortage shrinks it proportionally."""

    def test_chargeback_gross_basis_full_allocation(self, api, contract_admin_headers):
        """PRD §3.7: "The computed amount sums, over the referenced order's
        lines that are `ALLOCATED` or `PARTIALLY_ALLOCATED` and whose product
        `is_340b_contracted`, the difference between the product's
        `wholesale_acquisition_cost_cents` and its `contract_340b_price_cents`,
        multiplied by the line's allocated quantity."
        PRD §3.7: "on a fully allocated order the allocated quantities equal
        the requested ones and the chargeback captures the full WAC-to-contract
        delta".

        Gross basis: (10000 - 7000) x 10 = 30000.

        Design: Difficulty/dual_variant_calc/chargeback_gross_vs_net_basis
        """
        set_clock()
        _c, _p, order = setup_340b_allocated_order(
            wac_cents=10000, contract_cents=7000, quantity=10, shortage_pool=None
        )
        claim = submit_claim(order["id"], 30000)
        assert claim["computed_amount_cents"] == 30000, (
            f"gross basis (10000-7000) x 10 == 30000, got "
            f"{claim['computed_amount_cents']}"
        )
        assert claim["claim_status"] == ClaimStatus.SUBMITTED.value

    def test_chargeback_net_basis_under_shortage(self, api, contract_admin_headers):
        """PRD §3.7: "The computed amount sums, over the referenced order's
        lines that are `ALLOCATED` or `PARTIALLY_ALLOCATED` and whose product
        `is_340b_contracted`, the difference between the product's
        `wholesale_acquisition_cost_cents` and its `contract_340b_price_cents`,
        multiplied by the line's allocated quantity."
        PRD §3.7: "under shortage the allocated quantities shrink the
        chargeback proportionally — so the same claimed amount can match under
        one basis and mismatch under the other."

        Net basis: a PRO_RATA pool of 6 grants 6 of 10, so the chargeback is
        (10000 - 7000) x 6 = 18000 — diverging from the gross 30000 on
        identical prices and requested quantity.

        Design: Difficulty/dual_variant_calc/chargeback_gross_vs_net_basis
        """
        set_clock()
        _c, _p, order = setup_340b_allocated_order(
            wac_cents=10000, contract_cents=7000, quantity=10, shortage_pool=6
        )
        claim = submit_claim(order["id"], 18000)
        assert claim["computed_amount_cents"] == 18000, (
            f"net basis (10000-7000) x 6 == 18000, got "
            f"{claim['computed_amount_cents']}"
        )
        assert claim["computed_amount_cents"] != 30000


class TestClaimStateMachine:
    def _setup_submitted_claim(self, name_suffix=""):
        set_clock()
        _c, _p, order = setup_340b_allocated_order(
            wac_cents=10000, contract_cents=7000, quantity=10, shortage_pool=6
        )
        return submit_claim(order["id"], 18000)

    def test_claim_settle_from_submitted_rejected(self, api, contract_admin_headers):
        """PRD §3.7: "Settlement by a `ContractAdministrator` requires
        `VALIDATED` (`ERR_CLAIM_NOT_VALIDATED`) and lands in the terminal
        `SETTLED` state."

        Design: Corner/state_machines/claim_settle_from_submitted_rejected
        """
        claim = self._setup_submitted_claim()
        resp = api.settle_chargeback_claim(claim["id"], contract_admin_headers)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_VALIDATED)
        assert get_claim(claim["id"])["claim_status"] == ClaimStatus.SUBMITTED.value

    def test_deny_then_validate_claim_rejected(self, api, contract_admin_headers):
        """PRD §3.7: "Validation by a `ContractAdministrator` requires the
        claim to be `SUBMITTED` (`ERR_CLAIM_NOT_SUBMITTED`)".
        PRD §3.7: "Denial is available from either `SUBMITTED` or `VALIDATED`
        (`ERR_CLAIM_NOT_DENIABLE` otherwise) and lands in the terminal `DENIED`
        state."

        A DENIED claim is terminal: validation after denial is rejected.

        Design: Corner/errors/deny_then_validate_claim_rejected
        """
        claim = self._setup_submitted_claim()
        deny = api.deny_chargeback_claim(claim["id"], contract_admin_headers)
        assert validate_success(deny)["claim_status"] == ClaimStatus.DENIED.value

        resp = api.validate_chargeback_claim(claim["id"], contract_admin_headers)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_SUBMITTED)
        assert get_claim(claim["id"])["claim_status"] == ClaimStatus.DENIED.value


class TestClaimReferentialGates:
    def test_chargeback_on_non_340b_order_rejected(self, api, contract_admin_headers):
        """PRD §3.7: "The claim must reference an order flagged
        `is_340b_order`, a check applied both at submission and at validation
        (`ERR_NOT_340B_ORDER`, HTTP 422)."

        Design: Corner/validations/chargeback_on_non_340b_order_rejected
        """
        customer = create_customer(name="N340Rx")
        order = create_order(customer["id"], is_340b_order=False)
        resp = api.create_chargeback_claim(
            {"order_id": order["id"], "claimed_amount_cents": 100},
            contract_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_340B_ORDER)

    def test_claim_validate_amount_mismatch_rejected(self, api, contract_admin_headers):
        """PRD §3.7: "Validation by a `ContractAdministrator` requires the
        claim to be `SUBMITTED` (`ERR_CLAIM_NOT_SUBMITTED`), then re-verifies
        the 340B flag, then recomputes `computed_amount_cents` and requires it
        to equal `claimed_amount_cents` exactly (`ERR_CHARGEBACK_AMOUNT_MISMATCH`,
        HTTP 422)".

        The referential check fires independently on claim validation: the
        computed amount is 18000 but the claim asserts 99999.

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_referential_on_ship_and_claim
        """
        set_clock()
        _c, _p, order = setup_340b_allocated_order(
            wac_cents=10000, contract_cents=7000, quantity=10, shortage_pool=6
        )
        claim = submit_claim(order["id"], 99999)
        assert claim["computed_amount_cents"] == 18000

        resp = api.validate_chargeback_claim(claim["id"], contract_admin_headers)
        validate_error(resp, ApiErrorId.ERR_CHARGEBACK_AMOUNT_MISMATCH)
        assert get_claim(claim["id"])["claim_status"] == ClaimStatus.SUBMITTED.value
