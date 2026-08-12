"""Replacement claims: dual-variant credit, warranty windows, adjudication."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_claim,
    create_replacement_claim_payload,
    get_success_data,
    make_dealer_headers,
    setup_shipped_box_order,
    setup_shipped_door_order,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["plant_admin_headers"]


class TestClaimCreditVariants:
    def test_claim_provisional_estimate_is_flat_fifty_percent(self, api):
        """PRD §3.8: "Credit is valued against the dealer's current network
        standing, not history: `credit_basis_cents` is the original line's
        `unit_list_price_cents` multiplied by the dealer multiplier for the
        dealer's `price_level` as it stands at claim creation — using the same
        `L1` through `L5` schedule as order pricing — multiplied by the claimed
        `qty`, rounded half up to whole cents. The claim's first credit figure is
        a provisional estimate: `provisional_credit_cents` is a flat fifty percent
        of the basis, rounded half up, regardless of claim type or warranty
        window."

        Design: Difficulty/dual_variant_calc/claim_credit_provisional_vs_final_variant
        """
        env = setup_shipped_door_order(price_level="L4", qty=4, unit_price=30000, upcharge_pct=0.10)
        claim = create_claim(env, claim_type="FREIGHT_DAMAGE", qty=4)
        # basis = round_half_up(30,000 x 0.75 x 4) = 90,000.
        assert claim["credit_basis_cents"] == 90000
        assert claim["provisional_credit_cents"] == 45000, "the estimate is a flat 50% of basis"
        assert claim["status"] == "SUBMITTED"

    def test_in_window_freight_approval_pays_full_basis(self, api):
        """PRD §3.8: "An in-window approval of either covered type moves the claim
        to `APPROVED_NO_CHARGE` with `final_credit_cents` set to the full
        `credit_basis_cents` and `replacement_charge_cents` set to 0."
        PRD §3.8: "The provisional estimate and the final adjudication genuinely
        diverge: for identical claim data they differ whenever the final outcome
        is zero or one hundred percent of basis."

        Design: Difficulty/dual_variant_calc/claim_credit_provisional_vs_final_variant
        """
        env = setup_shipped_door_order(price_level="L4", qty=4, unit_price=30000, upcharge_pct=0.10)
        claim = create_claim(env, claim_type="FREIGHT_DAMAGE", qty=4)
        decided = validate_success(
            api.adjudicate_claim(claim["id"], {"decision": "APPROVE", "note": "carrier confirmed"}, ADMIN)
        )
        assert decided["status"] == "APPROVED_NO_CHARGE"
        assert decided["final_credit_cents"] == 90000, "in-window freight pays 100% of basis"
        assert decided["replacement_charge_cents"] == 0
        assert decided["provisional_credit_cents"] != decided["final_credit_cents"]

    def test_claim_dealer_error_charge_applied(self, api):
        """PRD §3.8: "`DEALER_ERROR` carries no warranty window at all: approving
        it moves the claim to `APPROVED_CHARGED` with `final_credit_cents` 0 and
        `replacement_charge_cents` set to sixty percent of the basis, rounded half
        up."
        PRD §3.8: "The claim's first credit figure is a provisional estimate:
        `provisional_credit_cents` is a flat fifty percent of the basis, rounded
        half up, regardless of claim type or warranty window."

        Design: Corner/calculations/claim_dealer_error_charge_applied
        """
        env = setup_shipped_door_order(price_level="L4", qty=4, unit_price=30000, upcharge_pct=0.10)
        claim = create_claim(env, claim_type="DEALER_ERROR", qty=2)
        # basis = round_half_up(30,000 x 0.75 x 2) = 45,000.
        assert claim["credit_basis_cents"] == 45000
        assert claim["provisional_credit_cents"] == 22500
        decided = validate_success(
            api.adjudicate_claim(claim["id"], {"decision": "APPROVE", "note": "dealer-caused"}, ADMIN)
        )
        assert decided["status"] == "APPROVED_CHARGED"
        assert decided["final_credit_cents"] == 0
        assert decided["replacement_charge_cents"] == 27000, "round_half_up(45,000 x 0.60)"


class TestClaimEligibility:
    def test_claim_line_not_eligible_box_line(self, api):
        """PRD §3.8: "Eligibility is strict: the referenced line must be a `DOOR`
        line, its order must be `SHIPPED`, the order must belong to the claiming
        dealer (the ownership check `ERR_RESOURCE_OWNERSHIP_MISMATCH` guards this
        first), and the claimed `qty` must not exceed the original line's `qty`;
        any failure is rejected with `ERR_CLAIM_LINE_NOT_ELIGIBLE` (HTTP 422)."

        Design: Corner/validations/claim_line_not_eligible_box_line
        """
        env = setup_shipped_box_order(price_level="L3", qty=2, unit_price=50000)
        resp = api.create_replacement_claim(
            create_replacement_claim_payload(env["line"]["id"], claim_type="FREIGHT_DAMAGE", qty=1),
            make_dealer_headers(env["dealer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_LINE_NOT_ELIGIBLE)


class TestWarrantyWindowBoundary:
    def _shipped_order_with_two_claims(self, api):
        env = setup_shipped_door_order(price_level="L4", qty=2, unit_price=30000, upcharge_pct=0.10)
        # A second DOOR line on a second shipped order keeps the claims
        # independent of each other's adjudication.
        env2 = setup_shipped_door_order(price_level="L4", qty=2, unit_price=30000, upcharge_pct=0.10)
        claim1 = create_claim(env, claim_type="FREIGHT_DAMAGE", qty=1)
        claim2 = create_claim(env2, claim_type="FREIGHT_DAMAGE", qty=1)
        return claim1, claim2

    def test_day_90_approve_within_window(self, api):
        """PRD §3.8: "Approving a `FREIGHT_DAMAGE` claim is allowed only within
        ninety days of `shipped_at`, and approving a `MANUFACTURING_DEFECT` claim
        only within three hundred sixty-five days; a claim exactly ninety — or
        exactly three hundred sixty-five — days after `shipped_at` is still within
        its window, while one day beyond is rejected with
        `ERR_CLAIM_WARRANTY_EXPIRED` (HTTP 422)."
        PRD §2.6: "An admin-only test-driving capability advances the logical
        clock to a supplied `to_iso8601` instant (ISO 8601 UTC); monotonicity is
        not enforced, so tests may set explicit instants."

        Design: Corner/validations/claim_warranty_window_boundary
        """
        claim1, _claim2 = self._shipped_order_with_two_claims(api)
        # shipped_at is the logical clock default 2026-05-01; 2026-07-30 is day 90.
        get_success_data(api.set_current_utc({"to_iso8601": "2026-07-30T00:00:00Z"}, ADMIN))
        decided = validate_success(api.adjudicate_claim(claim1["id"], {"decision": "APPROVE"}, ADMIN))
        assert decided["status"] == "APPROVED_NO_CHARGE", "exactly day 90 is within the window"

    def test_day_91_approve_rejected(self, api):
        """PRD §3.8: "Approving a `FREIGHT_DAMAGE` claim is allowed only within
        ninety days of `shipped_at`, and approving a `MANUFACTURING_DEFECT` claim
        only within three hundred sixty-five days; a claim exactly ninety — or
        exactly three hundred sixty-five — days after `shipped_at` is still within
        its window, while one day beyond is rejected with
        `ERR_CLAIM_WARRANTY_EXPIRED` (HTTP 422)."

        Design: Corner/validations/claim_warranty_window_boundary
        """
        _claim1, claim2 = self._shipped_order_with_two_claims(api)
        get_success_data(api.set_current_utc({"to_iso8601": "2026-07-31T00:00:00Z"}, ADMIN))
        resp = api.adjudicate_claim(claim2["id"], {"decision": "APPROVE"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_CLAIM_WARRANTY_EXPIRED)
        reread = validate_success(api.get_replacement_claim(claim2["id"], ADMIN))
        assert reread["status"] == "SUBMITTED", "a rejected adjudication must leave the claim open"


class TestAdjudicationTerminal:
    def test_adjudicate_claim_twice_rejected(self, api):
        """PRD §3.8: "Adjudication is a `PlantAdmin` decision carrying a `decision`
        of `APPROVE` or `DENY` and an optional `note` captured into
        `adjudicator_note`; the claim must still be in `SUBMITTED`, else
        `ERR_CLAIM_NOT_ADJUDICATABLE` (HTTP 409)."
        PRD §3.8: "Denying a claim of any type moves it to `DENIED` with both
        `final_credit_cents` and `replacement_charge_cents` set to 0. All three
        outcomes are terminal."

        Design: Corner/state_machines/adjudicate_claim_twice_rejected
        """
        env = setup_shipped_door_order(price_level="L4", qty=4, unit_price=30000, upcharge_pct=0.10)
        claim = create_claim(env, claim_type="FREIGHT_DAMAGE", qty=1)
        denied = validate_success(
            api.adjudicate_claim(claim["id"], {"decision": "DENY", "note": "insufficient evidence"}, ADMIN)
        )
        assert denied["status"] == "DENIED"
        resp = api.adjudicate_claim(claim["id"], {"decision": "APPROVE"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_ADJUDICATABLE)
        reread = validate_success(api.get_replacement_claim(claim["id"], ADMIN))
        assert reread["status"] == "DENIED"
