"""Main-extension design, provisional CIAC pricing, quote lifecycle, and expiry."""
from test_helpers import (
    ApiErrorId,
    ONE_ASPHALT_CROSSING,
    TWO_ASPHALT_CROSSINGS,
    confirm_booking,
    create_booking,
    create_crew,
    get_success_data,
    refresh_application,
    refresh_invoice,
    refresh_main_extension,
    set_clock,
    setup_ciac_pending_app,
    setup_design_app,
    setup_quoted_app,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestProvisionalCiacEvaluationOrder:
    def test_provisional_net_after_allowance(self, api, engineer_headers):
        """PRD §3.2: "First, the tariff allowance `allowance_ft` is one hundred feet plus twenty-five feet for each appliance row on the application."
        PRD §3.2: "Second, the `provisional_base_cost_cents` is the design footage priced at the standard unit cost of 4,500 cents per foot ($45.00)."
        PRD §3.2: "Fourth, the `provisional_net_ciac_cents` is the base cost plus surcharges minus the allowance footage priced at that same standard unit cost, floored at zero when the allowance would overtake the cost."

        Design: Difficulty/combinatorial_formula/ciac_gross_up_evaluation_order
        """
        ctx = setup_quoted_app(
            loads=[
                {"appliance_type": "FURNACE", "quantity": 1, "btuh_input_rating": 80000},
                {"appliance_type": "RANGE", "quantity": 1, "btuh_input_rating": 65000},
            ],
            design_footage_ft=200,
            crossings=TWO_ASPHALT_CROSSINGS,
            rock=False,
        )
        me = ctx["me"]
        assert me["allowance_ft"] == 150, (
            f"allowance = 100 + 25 x 2 rows = 150, got {me['allowance_ft']}"
        )
        assert me["provisional_base_cost_cents"] == 900000
        assert me["provisional_surcharges_cents"] == 30000
        assert me["provisional_net_ciac_cents"] == 255000, (
            f"930000 - 150 x 4500 = 255000, got {me['provisional_net_ciac_cents']}"
        )

    def test_gross_up_applies_to_net_only(self, api, clerk_headers):
        """PRD §3.2: "Fifth, the `provisional_gross_up_cents` is the tax gross-up on the net alone: the net multiplied by twenty-one seventy-ninths, rounded half up to whole cents."
        PRD §3.2: "The order is contractual: the gross-up base never includes the allowance offset, and the allowance is always valued at the standard unit cost."
        PRD §3.2: "Approval is a compound event: the main extension moves from `DESIGN_SUBMITTED` to `QUOTED`; a CIAC invoice is created with `amount_due_cents` equal to the provisional total due, in `ISSUED` status (or directly in `PAID` when that total is zero)"

        Design: Difficulty/combinatorial_formula/ciac_gross_up_evaluation_order
        """
        ctx = setup_quoted_app(
            loads=[
                {"appliance_type": "FURNACE", "quantity": 1, "btuh_input_rating": 80000},
                {"appliance_type": "RANGE", "quantity": 1, "btuh_input_rating": 65000},
            ],
            design_footage_ft=200,
            crossings=TWO_ASPHALT_CROSSINGS,
            rock=False,
        )
        me = ctx["me"]
        assert me["provisional_gross_up_cents"] == 67785, (
            f"round_half_up(255000 x 21/79) = 67785, got {me['provisional_gross_up_cents']}"
        )
        assert me["provisional_total_due_cents"] == 322785
        invoice = ctx["invoice"]
        assert invoice["amount_due_cents"] == 322785, (
            "the invoice mirrors the pinned-order provisional total"
        )
        assert invoice["status"] == "ISSUED"


class TestCommitmentDualDateVariants:
    def test_optimistic_and_conservative_dates_differ(self, api, rep_headers):
        """PRD §3.7: "The `optimistic_completion_date` assumes the fastest plausible path: when the design crosses anything (its `crossings_count` is greater than zero), ten calendar days of statutory-minimum permitting; then construction at one hundred fifty feet per day with the design footage divided by that rate and rounded up to whole days; then five days for the meter set."
        PRD §3.7: "The `conservative_completion_date` assumes the median path: twenty calendar days of jurisdiction-median permitting when crossings exist, construction at one hundred feet per day rounded up the same way, the same five meter-set days, and a further five-day buffer."

        Design: Difficulty/dual_variant_calc/commitment_dual_date_variants
        """
        ctx = setup_quoted_app(design_footage_ft=200, crossings=TWO_ASPHALT_CROSSINGS)
        commitment = ctx["commitment"]
        assert commitment["optimistic_completion_date"] == "2026-08-18", (
            f"10 + ceil(200/150) + 5 = 17 days from 2026-08-01, "
            f"got {commitment['optimistic_completion_date']}"
        )
        assert commitment["conservative_completion_date"] == "2026-09-02", (
            f"20 + ceil(200/100) + 5 + 5 = 32 days from 2026-08-01, "
            f"got {commitment['conservative_completion_date']}"
        )
        assert (
            commitment["optimistic_completion_date"]
            != commitment["conservative_completion_date"]
        )

    def test_committed_date_follows_conservative_variant(self, api, rep_headers):
        """PRD §3.7: "The `committed_completion_date` starts life equal to the conservative date."
        PRD §3.2: "a timeline commitment is born in `PROPOSED` with its `base_date` set to the approval date (§3.7)"

        Design: Difficulty/dual_variant_calc/commitment_dual_date_variants
        """
        ctx = setup_quoted_app(design_footage_ft=200, crossings=TWO_ASPHALT_CROSSINGS)
        commitment = ctx["commitment"]
        assert commitment["status"] == "PROPOSED"
        assert commitment["base_date"] == "2026-08-01", (
            f"base_date is the approval date, got {commitment['base_date']}"
        )
        assert commitment["committed_completion_date"] == "2026-09-02", (
            "committed starts at the conservative date"
        )


class TestZeroCiacChain:
    def test_zero_amount_invoice_auto_paid_at_creation(self, api, clerk_headers):
        """PRD §3.2: "Approval is a compound event: the main extension moves from `DESIGN_SUBMITTED` to `QUOTED`; a CIAC invoice is created with `amount_due_cents` equal to the provisional total due, in `ISSUED` status (or directly in `PAID` when that total is zero)"
        PRD §3.2: "Fourth, the `provisional_net_ciac_cents` is the base cost plus surcharges minus the allowance footage priced at that same standard unit cost, floored at zero when the allowance would overtake the cost."

        Design: Difficulty/transitive_cascade/accept_quote_zero_ciac_chain
        """
        ctx = setup_quoted_app(design_footage_ft=100, crossings=[])
        assert ctx["me"]["provisional_net_ciac_cents"] == 0, (
            "100 ft x 4500 - 125 ft x 4500 floors to zero"
        )
        assert ctx["invoice"]["status"] == "PAID", (
            f"zero-amount invoice auto-pays at creation, got {ctx['invoice']['status']}"
        )
        assert ctx["invoice"]["amount_due_cents"] == 0

    def test_accept_quote_walks_two_spine_hops(self, api, rep_headers):
        """PRD §3.2: "Acceptance moves the main extension from `QUOTED` to `ACCEPTED` and the application from `QUOTED` to `CIAC_PENDING`. When the invoice's amount due is zero, the zero-CIAC chain fires immediately: the invoice stands `PAID` without any payment being recorded, and the application continues straight through from `CIAC_PENDING` to `APPROVED_FOR_CONSTRUCTION` in the same breath."

        Design: Difficulty/transitive_cascade/accept_quote_zero_ciac_chain
        """
        ctx = setup_ciac_pending_app(design_footage_ft=100, crossings=[])
        assert ctx["me"]["status"] == "ACCEPTED", (
            f"the trigger's own transition lands ACCEPTED, got {ctx['me']['status']}"
        )
        assert ctx["app"]["status"] == "APPROVED_FOR_CONSTRUCTION", (
            f"the zero-CIAC chain skips CIAC_PENDING, got {ctx['app']['status']}"
        )


class TestDesignApprovalRbac:
    def test_builder_cannot_approve_design(self, api, clerk_headers, engineer_headers):
        """PRD §2.1: "A request whose role is not on the target endpoint's authorized-role list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: approve-design is listed for NewBusinessRep.
        PRD §3.2: "A `NewBusinessRep` then approves the design — possible only while the application itself sits in `DESIGN`, else `ERR_INVALID_STATE`."

        Design: Corner/rbac/builder_cannot_approve_design
        """
        ctx = setup_design_app(design_footage_ft=100, crossings=[])
        me_id = ctx["me"]["id"]
        from test_helpers import submit_design
        submit_design(me_id)

        resp = api.approve_design(me_id, ctx["builder_headers"])
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)

        me = refresh_main_extension(me_id)
        assert me["status"] == "DESIGN_SUBMITTED"
        resp = api.list_ciac_invoices(clerk_headers, params={"main_extension_id": me_id})
        _, meta = validate_paginated(resp)
        assert meta["total_count"] == 0, "a denied approval must not create an invoice"


class TestDesignRevision:
    def test_revise_after_payment_rejected(self, api, clerk_headers, engineer_headers):
        """PRD §3.2: "The engineer may send it back to draft — a revision that requires `expected_main_extension_version` to match (§2.7) and requires that no payment has ever been applied to the invoice, else `ERR_INVOICE_HAS_PAYMENTS` (HTTP 409)."

        Design: Corner/errors/revise_after_payment_rejected
        """
        ctx = setup_quoted_app(
            design_footage_ft=200, crossings=ONE_ASPHALT_CROSSING, rock=False
        )
        # Pay the invoice in full while the application is still QUOTED.
        from test_helpers import pay_invoice
        pay_invoice(ctx["invoice"]["id"], 446203)
        invoice = refresh_invoice(ctx["invoice"]["id"])
        assert invoice["status"] == "PAID"

        me = refresh_main_extension(ctx["me"]["id"])
        resp = api.revise_design(
            ctx["me"]["id"],
            {"expected_main_extension_version": me["version"], "design_footage_ft": 180},
            engineer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVOICE_HAS_PAYMENTS, expected_status=409)

        me_after = refresh_main_extension(ctx["me"]["id"])
        invoice_after = refresh_invoice(ctx["invoice"]["id"])
        assert me_after["status"] == "QUOTED"
        assert invoice_after["status"] == "PAID"


class TestQuoteExpiry:
    def test_accept_after_quote_valid_until_rejected(self, api, rep_headers):
        """PRD §3.2: "The builder may accept the quote — provided the acting builder owns the application and the current date has not passed `quote_valid_until`; acceptance on or before that date succeeds, and any later attempt is rejected with `ERR_QUOTE_EXPIRED` (HTTP 422)."
        PRD §2.9: "During the seven-day grace window itself the application remains `QUOTED`, but quote acceptance already fails with `ERR_QUOTE_EXPIRED`."

        Design: Corner/errors/quote_expired_accept_rejected
        """
        ctx = setup_quoted_app(design_footage_ft=100, crossings=[])
        app = refresh_application(ctx["app"]["id"])
        assert app["quote_valid_until"] == "2026-08-31", (
            f"approval date 2026-08-01 + 30 days, got {app['quote_valid_until']}"
        )

        set_clock("2026-09-03T09:00:00Z")
        resp = api.accept_quote(ctx["me"]["id"], ctx["builder_headers"])
        validate_error(resp, ApiErrorId.ERR_QUOTE_EXPIRED, expected_status=422)

        app_after = refresh_application(ctx["app"]["id"])
        me_after = refresh_main_extension(ctx["me"]["id"])
        assert app_after["status"] == "QUOTED", (
            "inside the grace window the sweep has not fired"
        )
        assert me_after["status"] == "QUOTED"

    def test_sweep_expires_quote_tree_after_grace(self, api, rep_headers):
        """PRD §3.9: "When the clock sweep of §2.9 finds an application still `QUOTED` more than seven days past its `quote_valid_until`, it moves the application to `EXPIRED` and cascades: the main extension follows from `QUOTED` to `EXPIRED`; the invoice is voided when nothing has been paid, or — with money already applied — moves from `ISSUED` or `PARTIALLY_PAID` to `REFUND_PENDING` with the full collected amount as `refund_required_cents`; and any non-terminal commitment is `CANCELLED`."

        Design: Corner/complexity_layers/quote_sweep_expires_after_grace
        """
        ctx = setup_quoted_app(
            design_footage_ft=200, crossings=ONE_ASPHALT_CROSSING, rock=False
        )
        set_clock("2026-09-08T09:00:00Z")

        app = refresh_application(ctx["app"]["id"])
        me = refresh_main_extension(ctx["me"]["id"])
        invoice = refresh_invoice(ctx["invoice"]["id"])
        commitment = get_success_data(
            api.get_timeline_commitment(ctx["commitment"]["id"], rep_headers)
        )
        assert app["status"] == "EXPIRED", (
            f"2026-09-08 is past 2026-08-31 + 7-day grace, got {app['status']}"
        )
        assert me["status"] == "EXPIRED"
        assert invoice["status"] == "VOID", "an unpaid invoice is voided by the sweep"
        assert commitment["status"] == "CANCELLED"


class TestDuplicateDesign:
    def test_duplicate_main_extension_rejected(self, api, engineer_headers):
        """PRD §3.2: "An application carries at most one non-`CANCELLED` main extension; a second attempt is rejected with `ERR_DUPLICATE_MAIN_EXTENSION` (HTTP 409)."

        Design: Corner/errors/duplicate_main_extension_rejected
        """
        ctx = setup_design_app(design_footage_ft=100, crossings=[])
        resp = api.create_main_extension(
            {
                "service_application_id": ctx["app"]["id"],
                "design_footage_ft": 150,
                "crossings": [],
                "rock_excavation_expected": False,
            },
            engineer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_MAIN_EXTENSION, expected_status=409)

        resp = api.list_main_extensions(
            engineer_headers, params={"service_application_id": ctx["app"]["id"]}
        )
        _, meta = validate_paginated(resp)
        assert meta["total_count"] == 1


class TestReadinessRead:
    def test_readiness_blockers_and_counters_track_booking(self, api, supervisor_headers):
        """PRD §3.1: "At any point, any authenticated role can read the application's computed posture: a readiness view reporting `readiness_posture` (`READY` when there is nothing outstanding, `BLOCKED` the moment any blocker exists), a `blockers` list whose entries come from the fixed vocabulary `CIAC_UNPAID`, `PERMIT_NOT_APPROVED`, `NO_CONFIRMED_BOOKING`, `METER_NOT_READY`, `TURN_ON_INCOMPLETE`, `GIS_NOT_VALIDATED`, and `ON_HOLD`, plus live counters derived from the child rows: `unpaid_ciac_cents`, `open_permit_count`, `confirmed_booking_count`, `verified_turn_on_count`, `active_load_count`, and the boolean `gis_validated`."

        Design: Corner/endpoints/readiness_posture_computed_read

        Note: PRD pins the blocker vocabulary and the live counters but is silent on
        the per-stage trigger conditions for the downstream blockers
        (METER_NOT_READY / TURN_ON_INCOMPLETE / GIS_NOT_VALIDATED), so no assertion
        is made on the full blocker set or a READY posture — only on the
        booking-driven blocker and the PRD-covered counters.
        """
        # Zero-CIAC path: after accept-quote the application sits in
        # APPROVED_FOR_CONSTRUCTION with the invoice already PAID.
        ctx = setup_ciac_pending_app(design_footage_ft=100, crossings=[])
        assert ctx["app"]["status"] == "APPROVED_FOR_CONSTRUCTION"

        first = validate_success(api.get_readiness(ctx["app"]["id"], supervisor_headers))
        assert first["readiness_posture"] == "BLOCKED"
        assert "NO_CONFIRMED_BOOKING" in first["blockers"]
        assert first["confirmed_booking_count"] == 0
        assert first["unpaid_ciac_cents"] == 0
        assert first["gis_validated"] is False

        crew = create_crew(specialty="SERVICE_LINE")
        booking = create_booking(ctx["app"]["id"], crew["id"], start=540, end=1020)
        confirm_booking(booking["id"])

        second = validate_success(api.get_readiness(ctx["app"]["id"], supervisor_headers))
        assert "NO_CONFIRMED_BOOKING" not in second["blockers"], (
            f"a CONFIRMED booking clears the booking blocker, got {second['blockers']}"
        )
        assert second["confirmed_booking_count"] == 1
        assert second["active_load_count"] == 1
