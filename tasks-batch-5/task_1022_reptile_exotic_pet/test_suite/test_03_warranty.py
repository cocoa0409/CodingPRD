"""Warranty-claim adjudication: branching resolution, refund cascade, gating, expiry."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS,
    make_customer_headers, make_store_manager_headers,
    setup_available_animal, create_customer, create_draft_sale,
    setup_fulfilled_sale, setup_approved_doa_claim,
)

_SALES = TEST_USERS["sales_associate_headers"]
_SM = TEST_USERS["store_manager_headers"]


class TestWarrantyClaimBranching:
    def test_resolve_refund_moves_sale_to_refunded_and_credits_wallet(self, api):
        """PRD §3.5: "Under `REFUND`, the sale moves from `FULFILLED` to `REFUNDED` and the customer's `wallet_credit_cents` increases by the claim's `refund_cents`."

        Design: Difficulty/non_linear_state_machine/warranty_claim_branching_refund_branch
        """
        ctx = setup_approved_doa_claim(api, sale_price_cents=18000)
        resolved = validate_success(api.resolve_claim(
            ctx["claim"]["id"], {"resolution": "REFUND"},
            headers=make_store_manager_headers("mgr-approve")))
        assert resolved["status"] == "RESOLVED"
        sale = get_success_data(api.get_sale(ctx["sale"]["id"], headers=_SM))
        assert sale["status"] == "REFUNDED"
        cust = get_success_data(api.get_customer(ctx["customer"]["id"], headers=_SM))
        assert cust["wallet_credit_cents"] == 18000

    def test_resolve_credit_moves_sale_to_closed_and_credits_wallet(self, api):
        """PRD §3.5: "Under `CREDIT`, the customer's `wallet_credit_cents` increases by `refund_cents` and the sale moves from `FULFILLED` to `CLOSED`."

        Design: Difficulty/non_linear_state_machine/warranty_claim_branching_refund_branch
        """
        ctx = setup_approved_doa_claim(api, sale_price_cents=18000)
        resolved = validate_success(api.resolve_claim(
            ctx["claim"]["id"], {"resolution": "CREDIT"},
            headers=make_store_manager_headers("mgr-approve")))
        assert resolved["status"] == "RESOLVED"
        sale = get_success_data(api.get_sale(ctx["sale"]["id"], headers=_SM))
        assert sale["status"] == "CLOSED"
        cust = get_success_data(api.get_customer(ctx["customer"]["id"], headers=_SM))
        assert cust["wallet_credit_cents"] == 18000


class TestWarrantyRefundCascade:
    def test_resolve_refund_cascades_sale_and_customer_wallet(self, api):
        """PRD §3.5: "Under `REFUND`, the sale moves from `FULFILLED` to `REFUNDED` and the customer's `wallet_credit_cents` increases by the claim's `refund_cents`."

        Design: Difficulty/transitive_cascade/warranty_refund_cascade_sale_to_customer_depth2
        """
        ctx = setup_approved_doa_claim(api, sale_price_cents=18000)
        validate_success(api.resolve_claim(
            ctx["claim"]["id"], {"resolution": "REFUND"},
            headers=make_store_manager_headers("mgr-approve")))
        sale = get_success_data(api.get_sale(ctx["sale"]["id"], headers=_SM))
        cust = get_success_data(api.get_customer(ctx["customer"]["id"], headers=_SM))
        assert sale["status"] == "REFUNDED"
        assert cust["wallet_credit_cents"] == 18000

    def test_wallet_credited_only_at_resolve_not_at_approve(self, api):
        """PRD §3.5: "On approval the claim moves to `APPROVED`, `approved_by_user_id` is stamped, and `refund_cents` is computed"
        PRD §3.5: "Under `REFUND`, the sale moves from `FULFILLED` to `REFUNDED` and the customer's `wallet_credit_cents` increases by the claim's `refund_cents`."

        Design: Difficulty/transitive_cascade/warranty_refund_cascade_sale_to_customer_depth2
        """
        ctx = setup_approved_doa_claim(api, sale_price_cents=18000)
        # after approve (not resolve) the wallet must still be 0
        before = get_success_data(api.get_customer(ctx["customer"]["id"], headers=_SM))
        assert before["wallet_credit_cents"] == 0
        validate_success(api.resolve_claim(
            ctx["claim"]["id"], {"resolution": "REFUND"},
            headers=make_store_manager_headers("mgr-approve")))
        after = get_success_data(api.get_customer(ctx["customer"]["id"], headers=_SM))
        assert after["wallet_credit_cents"] == 18000


class TestWarrantySubmissionRequiresFulfilledSale:
    def test_submit_against_confirmed_sale_returns_invalid_state(self, api):
        """PRD §3.5: "Once a sale is `FULFILLED`, its owning `Customer` may submit a **warranty claim** against it, supplying a `claim_type` (either `DOA` for dead-on-arrival or `EARLY_DEATH`) and a free-text `reason`."

        Design: Difficulty/cross_entity_state_dependency/warranty_submission_requires_sale_fulfilled
        """
        _, animal = setup_available_animal(
            api, animal_overrides={"list_price_cents": 12000, "acquisition_cost_cents": 3000})
        customer = create_customer(api, email="wsub-confirmed@x.com")
        sale = create_draft_sale(api, animal["id"], customer["id"])
        get_success_data(api.confirm_sale(sale["id"], headers=_SALES))  # CONFIRMED, not FULFILLED
        resp = api.create_warranty_claim(
            sale["id"], {"claim_type": "DOA", "reason": "too soon"},
            headers=make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_submit_against_fulfilled_sale_succeeds(self, api):
        """PRD §3.5: "Once a sale is `FULFILLED`, its owning `Customer` may submit a **warranty claim** against it" "A new claim starts `SUBMITTED`, with `resolution`, `refund_cents`, `replacement_animal_id`, and `approved_by_user_id` all empty"

        Design: Difficulty/cross_entity_state_dependency/warranty_submission_requires_sale_fulfilled
        """
        ctx = setup_fulfilled_sale(
            api,
            animal_overrides={"list_price_cents": 12000, "acquisition_cost_cents": 3000},
            customer_overrides={"email": "wsub-fulfilled@x.com"},
        )
        claim = validate_success(api.create_warranty_claim(
            ctx["sale"]["id"], {"claim_type": "DOA", "reason": "arrived dead"},
            headers=make_customer_headers(ctx["customer"]["id"])), expected_status=201)
        assert claim["status"] == "SUBMITTED"


class TestWarrantyInvalidAndExpired:
    def test_resolve_before_approve_returns_invalid_state(self, api):
        """PRD §3.5: "A `StoreManager` resolves an `APPROVED` claim, moving it to `RESOLVED"

        Design: Corner/state_machines/resolve_before_approve_returns_invalid_state
        """
        ctx = setup_fulfilled_sale(
            api,
            animal_overrides={"list_price_cents": 18000, "acquisition_cost_cents": 3000},
            customer_overrides={"email": "resolve-early@x.com"},
        )
        claim = get_success_data(api.create_warranty_claim(
            ctx["sale"]["id"], {"claim_type": "DOA", "reason": "x"},
            headers=make_customer_headers(ctx["customer"]["id"])))
        resp = api.resolve_claim(claim["id"], {"resolution": "REFUND"},
                                 headers=make_store_manager_headers("mgr-approve"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_approve_after_warranty_expiry_returns_warranty_expired(self, api):
        """PRD §3.5: "the logical clock is at or before the sale's `warranty_expires_at` (otherwise `ERR_WARRANTY_EXPIRED`)."

        Design: Corner/validations/warranty_approve_after_expiry_returns_warranty_expired
        """
        ctx = setup_fulfilled_sale(
            api,
            species_overrides={"warranty_days": 30},
            animal_overrides={"list_price_cents": 14000, "acquisition_cost_cents": 3000},
            customer_overrides={"email": "warr-expired@x.com"},
        )
        claim = get_success_data(api.create_warranty_claim(
            ctx["sale"]["id"], {"claim_type": "DOA", "reason": "late"},
            headers=make_customer_headers(ctx["customer"]["id"])))
        # confirmed at default clock 2026-07-01, warranty 30d -> expires 2026-07-31
        get_success_data(api.set_clock("2026-08-01T00:00:00Z", headers=_SM))
        resp = api.approve_claim(claim["id"], headers=make_store_manager_headers("mgr-approve"))
        validate_error(resp, ApiErrorId.ERR_WARRANTY_EXPIRED.value)
