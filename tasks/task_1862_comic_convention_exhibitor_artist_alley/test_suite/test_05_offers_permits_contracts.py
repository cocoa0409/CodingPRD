"""Offers, permits, deposits, pricing variants, and the path to contract."""
from test_helpers import (
    CLOCK_AFTER_EARLY_BIRD,
    ApiErrorId,
    assert_application,
    create_application,
    get_application,
    get_exhibitor,
    make_exhibitor_headers,
    record_guilty_issue,
    register_exhibitor,
    run_ops,
    set_clock,
    setup_accepted_with_placements,
    setup_contracted_application,
    setup_open_convention,
    setup_submitted_application,
    setup_two_applications_decided,
    submit_and_verify_permit,
    validate_error,
    validate_success,
    withdraw_application,
)

THREE_BOOTH_SPACES = [
    {
        "space_code": "A-101",
        "block": "A",
        "unit_number": 101,
        "hall": "MAIN",
        "kind": "BOOTH_10X10",
        "base_price_cents": 100000,
    },
    {
        "space_code": "A-102",
        "block": "A",
        "unit_number": 102,
        "hall": "MAIN",
        "kind": "BOOTH_10X10",
        "base_price_cents": 100000,
    },
    {
        "space_code": "A-103",
        "block": "A",
        "unit_number": 103,
        "hall": "MAIN",
        "kind": "BOOTH_10X10",
        "base_price_cents": 100000,
    },
]


class TestPermitLifecycle:
    def test_permit_expiry_via_run_ops_blocks_accept(self, api):
        """PRD §3.5: "Permits can also go stale: the run-ops permit sweep moves
        a `VERIFIED` permit whose `permit_expires_at` lies before the current
        clock to `EXPIRED`."
        PRD §3.5: "When the convention's `tax_permit_required` is true, the
        `permit_status` must be `VERIFIED` or `EXEMPT`
        (`ERR_PERMIT_NOT_VERIFIED`)."

        Design: Corner/state_machines/permit_expiry_via_run_ops_blocks_accept
        """
        bundle = setup_accepted_with_placements()
        app_id = bundle["application"]["id"]
        ex_id = bundle["exhibitor"]["id"]
        submit_and_verify_permit(
            app_id, ex_id, permit_expires_at="2026-09-01T00:00:00Z"
        )
        assert get_application(app_id)["permit_status"] == "VERIFIED"

        set_clock("2026-09-02T00:00:00Z")
        conv = run_ops(bundle["convention"]["id"])
        assert conv["ops_run_count"] == 1
        assert get_application(app_id)["permit_status"] == "EXPIRED"

        resp = api.accept_offer(
            app_id, {"deposit_cents": 22500}, make_exhibitor_headers(ex_id)
        )
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_VERIFIED)

    def test_accept_without_verified_permit_rejected(self, api):
        """PRD §3.5: "When the convention's `tax_permit_required` is true, the
        `permit_status` must be `VERIFIED` or `EXEMPT`
        (`ERR_PERMIT_NOT_VERIFIED`)."

        Design: Corner/validations/accept_without_verified_permit_rejected
        """
        bundle = setup_accepted_with_placements()  # permit never submitted
        app_id = bundle["application"]["id"]
        ex_id = bundle["exhibitor"]["id"]
        resp = api.accept_offer(
            app_id, {"deposit_cents": 22500}, make_exhibitor_headers(ex_id)
        )
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_VERIFIED)
        assert get_application(app_id)["permit_status"] == "PENDING"

    def test_exemption_claim_by_nonprofit_only(self, api):
        """PRD §3.5: "An exhibitor whose category is `NONPROFIT` may instead
        claim exemption, moving `PENDING` → `EXEMPT`; any other category is
        rejected with `ERR_EXEMPTION_NOT_ALLOWED`."

        Design: Corner/validations/exemption_claim_by_nonprofit_only
        """
        bundle = setup_open_convention(
            space_specs=[
                {
                    "space_code": "N-01",
                    "block": "N",
                    "unit_number": 1,
                    "hall": "SMALL_PRESS",
                    "kind": "NONPROFIT_TABLE",
                    "base_price_cents": 15000,
                }
            ],
            category_quotas=[
                {"category": "DEALER", "max_accepted": 1, "max_waitlisted": 1},
                {"category": "NONPROFIT", "max_accepted": 1, "max_waitlisted": 1},
            ],
            dock_doors=[],
        )
        conv_id = bundle["convention"]["id"]
        ex_np = register_exhibitor(legal_name="Charity Org", category="NONPROFIT")
        ex_de = register_exhibitor(legal_name="Dealer One LLC", category="DEALER")
        app_np = create_application(
            conv_id,
            ex_np["id"],
            category="NONPROFIT",
            requested_space_kinds=["NONPROFIT_TABLE"],
            estimated_daily_sales_cents=5000,
        )
        app_de = create_application(conv_id, ex_de["id"], category="DEALER")

        rejected = api.claim_exemption(
            app_de["id"], make_exhibitor_headers(ex_de["id"])
        )
        validate_error(rejected, ApiErrorId.ERR_EXEMPTION_NOT_ALLOWED)

        claimed = api.claim_exemption(
            app_np["id"], make_exhibitor_headers(ex_np["id"])
        )
        assert validate_success(claimed)["permit_status"] == "EXEMPT"


class TestOfferWindow:
    def test_accept_offer_after_deposit_window_rejected(self, api):
        """PRD §3.5: "The exhibitor must act within the deposit window — the
        clock must be on or before `decided_at` plus `deposit_window_days` days,
        or the attempt is rejected with `ERR_OFFER_EXPIRED`."

        Design: Corner/validations/accept_offer_after_deposit_window_rejected
        """
        bundle = setup_accepted_with_placements()
        app_id = bundle["application"]["id"]
        ex_id = bundle["exhibitor"]["id"]
        submit_and_verify_permit(app_id, ex_id)
        # decided_at was stamped at 2026-08-26T00:00:00Z; +14 days is
        # 2026-09-09T00:00:00Z, so 2026-09-10T00:00:01Z is past the window.
        set_clock("2026-09-10T00:00:01Z")
        resp = api.accept_offer(
            app_id, {"deposit_cents": 22500}, make_exhibitor_headers(ex_id)
        )
        validate_error(resp, ApiErrorId.ERR_OFFER_EXPIRED)
        assert get_application(app_id)["status"] == "JURIED_ACCEPTED"

    def test_offer_expiry_via_run_ops_declines_and_promotes(self, api):
        """PRD §3.5: "Offers also die of old age: the run-ops offer sweep
        declines any `JURIED_ACCEPTED` application whose `decided_at` plus
        `deposit_window_days` days lies strictly before the current clock,
        recording `OFFER_EXPIRED` as the reason in a system note and running the
        same release-and-promotion cascade."
        PRD §3.4: "Whenever a category's `accepted_count` decreases — an
        exhibitor declines, cancels, lets its offer expire, or is evicted — and
        the count is then below `max_accepted`, a promotion sweep fires for that
        convention and category."

        Design: Corner/state_machines/offer_expiry_via_run_ops_declines_and_promotes
        """
        bundle = setup_two_applications_decided()  # A ACCEPTED, B WAITLISTED
        # Offers were decided at 2026-08-26T00:00:00Z; +14 days expires
        # strictly before 2026-09-10.
        set_clock("2026-09-10T00:00:00Z")
        run_ops(bundle["convention"]["id"])
        app_a = get_application(bundle["application_a"]["id"])
        app_b = get_application(bundle["application_b"]["id"])
        assert app_a["status"] == "DECLINED"
        assert app_b["status"] == "JURIED_ACCEPTED"


class TestDepositMatching:
    def test_deposit_mismatch_on_accept_rejected(self, api):
        """PRD §3.5: "The `deposit_cents` is one quarter of the
        `final_invoice_cents`, rounded half-up to the nearest cent, and the
        request's `deposit_cents` must equal that computed figure exactly
        (`ERR_DEPOSIT_MISMATCH`)."

        Design: Corner/validations/deposit_mismatch_on_accept_rejected
        """
        bundle = setup_accepted_with_placements()
        app_id = bundle["application"]["id"]
        ex_id = bundle["exhibitor"]["id"]
        submit_and_verify_permit(app_id, ex_id)
        # Final invoice is 90000 (100000 less 10% early-bird); deposit 22500.
        resp = api.accept_offer(
            app_id, {"deposit_cents": 22499}, make_exhibitor_headers(ex_id)
        )
        validate_error(resp, ApiErrorId.ERR_DEPOSIT_MISMATCH)
        app = get_application(app_id)
        assert app["status"] == "JURIED_ACCEPTED"
        assert app["amount_paid_cents"] == 0
        assert app["final_invoice_cents"] is None


class TestPricingVariants:
    def test_provisional_quote_and_tax_estimate_at_submit(self, api):
        """PRD §3.3: "The provisional quote prices the request hypothetically:
        each of the `requested_space_count` spaces is priced at the cheapest
        `AVAILABLE` unit among the requested kinds — the lowest
        `base_price_cents` per requested kind — and any requested kind with no
        `AVAILABLE` unit at all is priced at that kind's floor: 95,000 cents for
        `BOOTH_10X10`, 175,000 for `BOOTH_10X20`, 140,000 for `CORNER_BOOTH`,
        160,000 for `ENDCAP`, 400,000 for `FEATURED_ISLAND`, 27,500 for
        `ARTIST_TABLE`, and 15,000 for `NONPROFIT_TABLE`."
        PRD §3.3: "The per-day tax is the application's
        `estimated_daily_sales_cents` multiplied by `sales_tax_rate_bp` and
        divided by ten thousand, rounded half-up to the nearest cent; the
        `tax_estimate_cents` is that rounded per-day figure multiplied by the
        number of selling days."

        Design: Difficulty/dual_variant_calc/provisional_quote_vs_final_invoice_space_count_divergence
        """
        bundle = setup_submitted_application(
            space_count=3, estimated_daily_sales_cents=33333
        )
        app = bundle["application"]
        assert_application(app)
        # 3 hypothetical spaces at the cheapest AVAILABLE 100000: subtotal
        # 300000 -> 10% multi-space + 10% early-bird, single rounding.
        assert app["provisional_quote_cents"] == 240000
        # round_half_up(33333 * 875 / 10000) = 2917 per day x 4 selling days.
        assert app["tax_estimate_cents"] == 11668

    def test_final_invoice_diverges_from_provisional(self, api):
        """PRD §3.5: "The final variant of the pricing ladder (§3.3) runs over
        the spaces actually held for the application — the convention's
        `RESERVED` units whose `current_application_id` is this application —
        with the space count taken from those units and the demand-tier
        multiplier read from the sold count at accept time; identical
        application inputs can therefore price differently from the provisional
        quote."
        PRD §3.5: "On success the application becomes `CONTRACTED`: the invoice
        and deposit are persisted, `amount_paid_cents` is set to the deposit,
        and `balance_due_cents` opens at the invoice minus the amount paid plus
        any `badge_fees_cents` (zero at this point, since badge extras only
        become purchasable after placement)."

        Design: Difficulty/dual_variant_calc/provisional_quote_vs_final_invoice_space_count_divergence
        """
        bundle = setup_contracted_application(
            space_count=3, estimated_daily_sales_cents=33333, deposit_cents=22500
        )
        app = bundle["application"]
        assert_application(app)
        assert app["status"] == "CONTRACTED"
        # Provisional priced 3 hypothetical spaces; the final variant prices the
        # single RESERVED unit: subtotal 100000, early-bird 10% only.
        assert app["provisional_quote_cents"] == 240000
        assert app["final_invoice_cents"] == 90000
        assert app["provisional_quote_cents"] != app["final_invoice_cents"]
        assert app["deposit_cents"] == 22500
        assert app["amount_paid_cents"] == 22500
        assert app["balance_due_cents"] == 67500

    def test_final_invoice_discount_keyed_on_prediscount_subtotal(self, api):
        """PRD §3.3: "A multi-space discount reads off that pre-discount
        subtotal — never off the discounted value: a subtotal of at least
        300,000 cents earns ten percent off; at least 150,000 cents but below
        300,000 earns five percent; anything lower earns none."

        Design: Difficulty/combinatorial_formula/final_invoice_discount_keyed_on_prediscount_subtotal
        """
        bundle = setup_contracted_application(
            space_specs=THREE_BOOTH_SPACES,
            space_count=3,
            clock=CLOCK_AFTER_EARLY_BIRD,  # no early-bird deduction
            placement_space_codes=["A-101", "A-102", "A-103"],
            deposit_cents=67500,
        )
        app = bundle["application"]
        # Subtotal 300000 keyed on the PRE-discount value earns 10%:
        # 300000 * 0.90 = 270000. Keying on the discounted value would wrongly
        # select 5% (300000 * 0.95 = 285000).
        assert app["final_invoice_cents"] == 270000
        assert app["final_invoice_cents"] != 285000

    def test_deposit_and_balance_after_multi_space_accept(self, api):
        """PRD §3.5: "The `deposit_cents` is one quarter of the
        `final_invoice_cents`, rounded half-up to the nearest cent, and the
        request's `deposit_cents` must equal that computed figure exactly
        (`ERR_DEPOSIT_MISMATCH`)."
        PRD §3.5: "On success the application becomes `CONTRACTED`: the invoice
        and deposit are persisted, `amount_paid_cents` is set to the deposit,
        and `balance_due_cents` opens at the invoice minus the amount paid plus
        any `badge_fees_cents` (zero at this point, since badge extras only
        become purchasable after placement)."

        Design: Difficulty/combinatorial_formula/final_invoice_discount_keyed_on_prediscount_subtotal
        """
        bundle = setup_contracted_application(
            space_specs=THREE_BOOTH_SPACES,
            space_count=3,
            clock=CLOCK_AFTER_EARLY_BIRD,
            placement_space_codes=["A-101", "A-102", "A-103"],
            deposit_cents=67500,
        )
        app = bundle["application"]
        assert app["deposit_cents"] == 67500  # round_half_up(270000 * 0.25)
        assert app["amount_paid_cents"] == 67500
        assert app["balance_due_cents"] == 202500

    def test_deposit_rounding_half_up_on_quarter(self, api):
        """PRD §3.5: "The `deposit_cents` is one quarter of the
        `final_invoice_cents`, rounded half-up to the nearest cent, and the
        request's `deposit_cents` must equal that computed figure exactly
        (`ERR_DEPOSIT_MISMATCH`)."
        PRD §2.6: "Wherever a computation produces a fractional cent or a
        fractional score, the system rounds half up, and the exact points where
        rounding occurs are pinned per calculation in Section 3"

        Design: Corner/calculations/deposit_rounding_half_up_on_quarter
        """
        bundle = setup_contracted_application(
            space_specs=[
                {
                    "space_code": "A-101",
                    "block": "A",
                    "unit_number": 101,
                    "hall": "MAIN",
                    "kind": "BOOTH_10X10",
                    "base_price_cents": 100030,
                }
            ],
            deposit_cents=22507,
        )
        app = bundle["application"]
        # round_half_up(100030 * 0.90) = 90027
        assert app["final_invoice_cents"] == 90027
        # round_half_up(90027 * 0.25) = round_half_up(22506.75) = 22507
        assert app["deposit_cents"] == 22507
        assert app["balance_due_cents"] == 67520


class TestAcceptOfferGates:
    def test_accept_offer_withdrawn_with_wrong_deposit_yields_invalid_transition(
        self, api
    ):
        """PRD §3.5: "Consistent with the global validation order, a request
        failing several of these surfaces the out-of-state rejection before the
        window check, the window check before the standing and permit gates,
        and the deposit comparison last of all."
        PRD §2.8: "A single request can fail several checks at once. Which
        rejection it receives is decided by a fixed priority order; the priority
        position, not the numeric HTTP status, decides which error surfaces when
        several checks fail."

        Design: Difficulty/priority_pair_validation_conflict/accept_offer_state_precedes_fiscal
        """
        bundle = setup_submitted_application()
        app_id = bundle["application"]["id"]
        ex_id = bundle["exhibitor"]["id"]
        withdraw_application(app_id, ex_id)
        # Both gates fail: the state gate (WITHDRAWN is not a from-state) and
        # the deposit gate (1 cent never matches the computed deposit).
        resp = api.accept_offer(
            app_id, {"deposit_cents": 1}, make_exhibitor_headers(ex_id)
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)

    def test_accept_offer_rejection_leaves_withdrawn_state_untouched(self, api):
        """PRD §3.3: "`WITHDRAWN` is terminal."
        PRD §3.5: "On success the application becomes `CONTRACTED`: the invoice
        and deposit are persisted, `amount_paid_cents` is set to the deposit,
        and `balance_due_cents` opens at the invoice minus the amount paid plus
        any `badge_fees_cents` (zero at this point, since badge extras only
        become purchasable after placement)."

        Design: Difficulty/priority_pair_validation_conflict/accept_offer_state_precedes_fiscal
        """
        bundle = setup_submitted_application()
        app_id = bundle["application"]["id"]
        ex_id = bundle["exhibitor"]["id"]
        withdraw_application(app_id, ex_id)
        resp = api.accept_offer(
            app_id, {"deposit_cents": 1}, make_exhibitor_headers(ex_id)
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)
        app = get_application(app_id)
        assert app["status"] == "WITHDRAWN"
        assert app["final_invoice_cents"] is None
        assert app["deposit_cents"] is None
        assert app["amount_paid_cents"] == 0

    def test_accept_offer_rejected_when_exhibitor_suspended(self, api):
        """PRD §3.5: "The exhibitor's `standing` must be `GOOD` or `PROBATION`
        (`ERR_EXHIBITOR_SUSPENDED`)."

        Design: Difficulty/cross_entity_state_dependency/accept_offer_blocked_by_exhibitor_standing
        """
        bundle = setup_accepted_with_placements()
        app_id = bundle["application"]["id"]
        ex_id = bundle["exhibitor"]["id"]
        conv_id = bundle["convention"]["id"]
        submit_and_verify_permit(app_id, ex_id)
        # Two CRITICAL guilty findings: 3 + 3 = 6 strike points -> SUSPENDED.
        record_guilty_issue(conv_id, ex_id, "CRITICAL", "Incident one")
        record_guilty_issue(conv_id, ex_id, "CRITICAL", "Incident two")
        assert get_exhibitor(ex_id)["standing"] == "SUSPENDED"

        resp = api.accept_offer(
            app_id, {"deposit_cents": 22500}, make_exhibitor_headers(ex_id)
        )
        validate_error(resp, ApiErrorId.ERR_EXHIBITOR_SUSPENDED)

    def test_suspended_exhibitor_application_stays_juried_accepted(self, api):
        """PRD §3.5: "The exhibitor's `standing` must be `GOOD` or `PROBATION`
        (`ERR_EXHIBITOR_SUSPENDED`)."
        PRD §3.5: "On success the application becomes `CONTRACTED`: the invoice
        and deposit are persisted, `amount_paid_cents` is set to the deposit,
        and `balance_due_cents` opens at the invoice minus the amount paid plus
        any `badge_fees_cents` (zero at this point, since badge extras only
        become purchasable after placement)."

        Design: Difficulty/cross_entity_state_dependency/accept_offer_blocked_by_exhibitor_standing
        """
        bundle = setup_accepted_with_placements()
        app_id = bundle["application"]["id"]
        ex_id = bundle["exhibitor"]["id"]
        conv_id = bundle["convention"]["id"]
        submit_and_verify_permit(app_id, ex_id)
        record_guilty_issue(conv_id, ex_id, "CRITICAL", "Incident one")
        record_guilty_issue(conv_id, ex_id, "CRITICAL", "Incident two")

        resp = api.accept_offer(
            app_id, {"deposit_cents": 22500}, make_exhibitor_headers(ex_id)
        )
        validate_error(resp, ApiErrorId.ERR_EXHIBITOR_SUSPENDED)
        app = get_application(app_id)
        assert app["status"] == "JURIED_ACCEPTED"
        assert app["final_invoice_cents"] is None
        assert app["deposit_cents"] is None
