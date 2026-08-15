"""Home-sale assistance: eligibility gate, uniqueness, loss-basis variants, cap."""
from test_helpers import (
    api_client,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_case_in_progress,
    create_home_sale,
    create_home_sale_payload,
)

MC = TEST_USERS["coordinator_headers"]
FIN = TEST_USERS["finance_headers"]

EXEC_HOMEOWNER_POLICY = {
    "job_level": "EXECUTIVE",
    "home_ownership": "HOMEOWNER",
    "hhg_cap_cents": 900000,
    "temp_housing_cap_cents": 600000,
    "temp_housing_max_nights": 60,
    "travel_cap_cents": 200000,
    "loss_on_sale_cap_cents": 4000000,
    "misc_cap_cents": 300000,
    "home_sale_eligible": True,
}
EXEC_HOMEOWNER_EMPLOYEE = {"job_level": "EXECUTIVE", "home_ownership": "HOMEOWNER"}


def _eligible_ctx(**policy_overrides):
    """EXECUTIVE/DOMESTIC/HOMEOWNER home-sale-eligible case IN_PROGRESS."""
    overrides = dict(EXEC_HOMEOWNER_POLICY)
    overrides.update(policy_overrides)
    return create_case_in_progress(policy_overrides=overrides,
                                   employee_overrides=dict(EXEC_HOMEOWNER_EMPLOYEE))


class TestHomeSaleGateAndUniqueness:
    def test_renter_home_sale_rejected(self):
        """PRD §3.6: "The gate is twofold: a tier whose `home_sale_eligible`
        flag is false rejects the attempt with `ERR_HOME_SALE_NOT_ELIGIBLE`"

        Design: Corner/validations/renter_home_sale_rejected
        """
        ctx = create_case_in_progress()  # default tier is not home-sale eligible
        resp = api_client.create_home_sale(
            create_home_sale_payload(ctx["case"]["id"]), MC)
        validate_error(resp, ApiErrorId.ERR_HOME_SALE_NOT_ELIGIBLE)

    def test_second_home_sale_for_same_case_rejected(self):
        """PRD §3.6: "because each case admits exactly one home-sale
        transaction, a second program for the same case is rejected with
        `ERR_DUPLICATE_RESOURCE`."
        PRD §3.6: "A case's home-sale collection returns at most one element."

        Design: Corner/validations/second_home_sale_for_same_case_rejected
        """
        ctx = _eligible_ctx()
        case_id = ctx["case"]["id"]
        first = create_home_sale(case_id)
        assert first["status"] == "LISTED"

        resp = api_client.create_home_sale(
            create_home_sale_payload(case_id, appraised_value_cents=51000000,
                                     original_purchase_price_cents=49000000,
                                     list_price_cents=53000000), MC)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE)

        data, meta = validate_paginated(api_client.list_case_home_sales(case_id, MC))
        assert len(data) == 1
        assert data[0]["id"] == first["id"]


class TestLossBasisVariants:
    def test_loss_on_sale_appraised_basis(self):
        """PRD §3.6: "Under an `APPRAISED` basis, `gross_loss_cents` is the
        larger of zero and the appraised value minus the sale price"
        PRD §3.6: "The payable benefit, `capped_benefit_cents`, is the smaller
        of the gross loss and the effective loss-on-sale cap"
        PRD §3.6: "At that moment the system copies the policy's `loss_basis`
        into the transaction's `loss_basis_used` and computes the benefit."

        Design: Difficulty/dual_variant_calc/loss_on_sale_appraised_vs_purchase
        """
        ctx = _eligible_ctx(loss_basis="APPRAISED")
        case_id = ctx["case"]["id"]
        hs = create_home_sale(case_id, appraised_value_cents=50000000,
                              original_purchase_price_cents=48000000,
                              list_price_cents=52000000)
        # Until the sale is recorded the computed fields are null (PRD §3.6).
        assert hs["gross_loss_cents"] is None
        assert hs["capped_benefit_cents"] is None
        assert hs["loss_basis_used"] is None

        sold = get_success_data(api_client.record_sale(
            hs["id"], {"sale_price_cents": 45000000}, MC))
        assert sold["status"] == "SOLD"
        assert sold["loss_basis_used"] == "APPRAISED"
        # max(0, 50000000 - 45000000) = 5000000; min(5000000, 4000000) caps it.
        assert sold["gross_loss_cents"] == 5000000
        assert sold["capped_benefit_cents"] == 4000000

    def test_loss_on_sale_purchase_price_basis(self):
        """PRD §3.6: "under `PURCHASE_PRICE`, it is the larger of zero and the
        original purchase price minus the sale price. Identical sale data can
        therefore yield different gross losses under the two bases."

        Design: Difficulty/dual_variant_calc/loss_on_sale_appraised_vs_purchase
        """
        ctx = create_case_in_progress(
            policy_overrides={"job_level": "MANAGER",
                              "move_scope": "INTERNATIONAL",
                              "home_ownership": "HOMEOWNER",
                              "home_sale_eligible": True,
                              "loss_on_sale_cap_cents": 4000000,
                              "loss_basis": "PURCHASE_PRICE"},
            employee_overrides={"job_level": "MANAGER", "home_ownership": "HOMEOWNER"},
            case_overrides={"move_scope": "INTERNATIONAL",
                            "destination_city": "London"})
        case_id = ctx["case"]["id"]
        hs = create_home_sale(case_id, appraised_value_cents=50000000,
                              original_purchase_price_cents=48000000,
                              list_price_cents=52000000)

        sold = get_success_data(api_client.record_sale(
            hs["id"], {"sale_price_cents": 45000000}, MC))
        assert sold["status"] == "SOLD"
        assert sold["loss_basis_used"] == "PURCHASE_PRICE"
        # max(0, 48000000 - 45000000) = 3000000; min(3000000, 4000000) keeps it.
        assert sold["gross_loss_cents"] == 3000000
        assert sold["capped_benefit_cents"] == 3000000


class TestCapMinInteraction:
    def test_loss_on_sale_cap_min_interaction_cap_binds(self):
        """PRD §3.6: "Under an `APPRAISED` basis, `gross_loss_cents` is the
        larger of zero and the appraised value minus the sale price"
        PRD §3.6: "The payable benefit, `capped_benefit_cents`, is the smaller
        of the gross loss and the effective loss-on-sale cap — the policy's
        `loss_on_sale_cap_cents` plus the approved `LOSS_ON_SALE` exception
        increases for the case."

        Design: Difficulty/combinatorial_formula/loss_on_sale_cap_min_interaction
        """
        ctx = _eligible_ctx(loss_basis="APPRAISED")
        hs = create_home_sale(ctx["case"]["id"], appraised_value_cents=60000000,
                              original_purchase_price_cents=55000000,
                              list_price_cents=61000000)
        sold = get_success_data(api_client.record_sale(
            hs["id"], {"sale_price_cents": 52000000}, MC))
        assert sold["status"] == "SOLD"
        # Inner layer: max(0, 60000000 - 52000000) = 8000000.
        assert sold["gross_loss_cents"] == 8000000
        # Outer layer: min(8000000, 4000000) — the cap binds.
        assert sold["capped_benefit_cents"] == 4000000

    def test_loss_on_sale_max_zero_floor_when_sale_exceeds_basis(self):
        """PRD §3.6: "Under an `APPRAISED` basis, `gross_loss_cents` is the
        larger of zero and the appraised value minus the sale price"

        Design: Difficulty/combinatorial_formula/loss_on_sale_cap_min_interaction
        """
        ctx = _eligible_ctx(loss_basis="APPRAISED")
        hs = create_home_sale(ctx["case"]["id"], appraised_value_cents=60000000,
                              original_purchase_price_cents=55000000,
                              list_price_cents=61000000)
        # Sale price above the appraised value: the loss floors at zero.
        sold = get_success_data(api_client.record_sale(
            hs["id"], {"sale_price_cents": 62000000}, MC))
        assert sold["gross_loss_cents"] == 0
        assert sold["capped_benefit_cents"] == 0
        assert sold["status"] == "SOLD"
