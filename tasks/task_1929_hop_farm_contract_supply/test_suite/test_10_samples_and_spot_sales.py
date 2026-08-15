"""Brewery samples and the spot-sale channel: resend loop, reserve/confirm/
cancel, the selected-sample gate, and the credit-limit gate."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_pellet_lot_single_source, create_sample, decide_sample,
    create_spot_sale, TEST_USERS,
)

CM = TEST_USERS["contract_manager_headers"]


def _setup_pellet_736(api):
    """One AVAILABLE pellet lot of 736 lbs (single source, dried 800)."""
    ctx = setup_pellet_lot_single_source(wet_lbs=3000, dried_lbs=800)
    assert ctx["pellet"]["qty_lbs"] == 736
    return ctx["pellet"]


class TestSampleResendLoop:
    def test_resend_after_rejection_increments_round(self, api, contract_manager_headers):
        """PRD §3.7: "Each sample carries a system-assigned `sample_round`: 1
        plus the count of all prior samples for the same lot-and-brewery pair."
        and "Rejection does not close the door: a fresh sample may be sent to the
        same brewery for the same lot, and it is created with the next
        `sample_round`, forming a resend loop at the pair level."

        Design: Corner/state_machines/sample_resend_after_rejection_increments_round
        """
        pellet = _setup_pellet_736(api)
        first = create_sample(pellet["id"], "CraftBrew")
        assert first["sample_round"] == 1
        assert first["status"] == "SENT"
        decide_sample(first["id"], "REJECTED")
        second = create_sample(pellet["id"], "CraftBrew")
        assert second["sample_round"] == 2
        assert second["status"] == "SENT"


class TestSpotReserveAndCancel:
    def test_draft_then_cancel_releases_lot(self, api, contract_manager_headers):
        """PRD §3.7: "the sale snapshots the lot's full `qty_lbs` into its own
        `qty_lbs` at draft time, the lot moves from `AVAILABLE` to `RESERVED`,
        and the sale opens in `DRAFT` with its `sale_total_cents` null until
        confirmation. ... Cancelling a draft sale moves it to `CANCELLED` and
        returns the lot from `RESERVED` to `AVAILABLE`."

        Design: Corner/state_machines/spot_reserve_cancel_releases_lot
        """
        pellet = _setup_pellet_736(api)
        sale = create_spot_sale(pellet["id"], buyer_name="CraftBrew",
                                price_cents_per_lb=650,
                                buyer_credit_limit_cents=1_000_000)
        assert sale["status"] == "DRAFT"
        assert sale["qty_lbs"] == 736
        assert sale["sale_total_cents"] is None
        mid = validate_success(api.get_pellet_lot(pellet["id"], contract_manager_headers), 200)
        assert mid["inventory_status"] == "RESERVED"
        cancelled = validate_success(
            api.cancel_spot_sale(sale["id"], contract_manager_headers), 200)
        assert cancelled["status"] == "CANCELLED"
        after = validate_success(
            api.get_pellet_lot(pellet["id"], contract_manager_headers), 200)
        assert after["inventory_status"] == "AVAILABLE"


class TestSpotConfirmHappyPath:
    def test_confirm_with_selected_sample_at_exact_credit_limit(
            self, api, contract_manager_headers):
        """PRD §3.7: "Second, the fiscal gate: the sale's `qty_lbs` times its
        `price_cents_per_lb` must not exceed the `buyer_credit_limit_cents`,
        otherwise `ERR_CREDIT_LIMIT_EXCEEDED`. A successful confirmation sets
        `sale_total_cents` to that product and moves the lot from `RESERVED` to
        `SOLD`." At 736 x 650 = 478400 against a limit of exactly 478400 the
        not-exceed gate passes.

        Design: Corner/endpoints/spot_sale_confirm_happy_path
        """
        pellet = _setup_pellet_736(api)
        sample = create_sample(pellet["id"], "CraftBrew")
        decide_sample(sample["id"], "SELECTED")
        sale = create_spot_sale(pellet["id"], buyer_name="CraftBrew",
                                price_cents_per_lb=650,
                                buyer_credit_limit_cents=478400)
        confirmed = validate_success(
            api.confirm_spot_sale(sale["id"], contract_manager_headers), 200)
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["sale_total_cents"] == 478400
        lot = validate_success(api.get_pellet_lot(pellet["id"], contract_manager_headers), 200)
        assert lot["inventory_status"] == "SOLD"


class TestSelectedSampleGate:
    def test_rejected_sample_does_not_satisfy_gate(self, api, contract_manager_headers):
        """PRD §3.7: "First, the quality gate: a sample with the sale's
        `pellet_lot_id` and `buyer_name` must exist in `SELECTED` status,
        otherwise `ERR_SAMPLE_NOT_SELECTED`."

        Design: Difficulty/cross_entity_state_dependency/spot_confirm_requires_selected_sample
        """
        pellet = _setup_pellet_736(api)
        sale = create_spot_sale(pellet["id"], buyer_name="CraftBrew",
                                price_cents_per_lb=650,
                                buyer_credit_limit_cents=1_000_000)
        sample = create_sample(pellet["id"], "CraftBrew")
        decide_sample(sample["id"], "REJECTED")
        res = api.confirm_spot_sale(sale["id"], contract_manager_headers)
        validate_error(res, ApiErrorId.ERR_SAMPLE_NOT_SELECTED)
        sale_after = validate_success(
            api.get_spot_sale(sale["id"], contract_manager_headers), 200)
        assert sale_after["status"] == "DRAFT"
        lot_after = validate_success(
            api.get_pellet_lot(pellet["id"], contract_manager_headers), 200)
        assert lot_after["inventory_status"] == "RESERVED"

    def test_no_sample_at_all_fails_gate(self, api, contract_manager_headers):
        """PRD §3.7: "First, the quality gate: a sample with the sale's
        `pellet_lot_id` and `buyer_name` must exist in `SELECTED` status,
        otherwise `ERR_SAMPLE_NOT_SELECTED`." With no sample ever sent for the
        pair, none exists in SELECTED status.

        Design: Difficulty/cross_entity_state_dependency/spot_confirm_requires_selected_sample
        """
        pellet = _setup_pellet_736(api)
        sale = create_spot_sale(pellet["id"], buyer_name="CraftBrew",
                                price_cents_per_lb=650,
                                buyer_credit_limit_cents=1_000_000)
        res = api.confirm_spot_sale(sale["id"], contract_manager_headers)
        validate_error(res, ApiErrorId.ERR_SAMPLE_NOT_SELECTED)


class TestStateBeatsFiscalPriority:
    def _setup_cancelled_sale_over_limit(self, api):
        """A spot sale (price 700, credit limit 100) drafted against a 736-lb
        lot and then cancelled. The fiscal check would also fail:
        736 x 700 = 515200 > 100."""
        pellet = _setup_pellet_736(api)
        sale = create_spot_sale(pellet["id"], buyer_name="CraftBrew",
                                price_cents_per_lb=700,
                                buyer_credit_limit_cents=100)
        validate_success(api.cancel_spot_sale(sale["id"], CM), 200)
        return pellet, sale

    def test_state_error_masks_credit_limit_error(self, api, contract_manager_headers):
        """PRD §2.8: "When several checks could fail on the same request, the
        system reports failures in a fixed priority order so callers see the most
        fundamental problem first, and a failure at any tier masks every lower
        tier." — "6. State-machine from-state — the target resource is in a
        state from which the requested transition exists, else
        `ERR_INVALID_STATE`." outranks "13. The buyer credit-limit check at
        spot-sale confirm, else `ERR_CREDIT_LIMIT_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/spot_confirm_state_beats_fiscal
        """
        pellet, sale = self._setup_cancelled_sale_over_limit(api)
        res = api.confirm_spot_sale(sale["id"], contract_manager_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_rejected_confirm_has_no_side_effects(self, api, contract_manager_headers):
        """PRD §3.7: "A successful confirmation sets `sale_total_cents` to that
        product and moves the lot from `RESERVED` to `SOLD`. Cancelling a draft
        sale moves it to `CANCELLED` and returns the lot from `RESERVED` to
        `AVAILABLE`." A confirm rejected at the state tier is not a successful
        confirmation, so neither effect fires.

        Design: Difficulty/priority_pair_validation_conflict/spot_confirm_state_beats_fiscal
        """
        pellet, sale = self._setup_cancelled_sale_over_limit(api)
        validate_error(api.confirm_spot_sale(sale["id"], contract_manager_headers),
                       ApiErrorId.ERR_INVALID_STATE)
        sale_after = validate_success(
            api.get_spot_sale(sale["id"], contract_manager_headers), 200)
        assert sale_after["status"] == "CANCELLED"
        lot_after = validate_success(
            api.get_pellet_lot(pellet["id"], contract_manager_headers), 200)
        assert lot_after["inventory_status"] == "AVAILABLE"
