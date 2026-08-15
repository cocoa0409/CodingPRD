"""Submission fees, tier boundaries, and refund policy (PRD §3.2)."""
from test_helpers import (
    ApiErrorId,
    fx_invited,
    make_filmmaker_headers,
    set_clock, st_advance, st_edition, st_film, st_rule, st_submitter,
    validate_error, validate_success,
)


def _open_ctx(**edition_over):
    ctx = st_edition(edition_over=edition_over or None)
    st_advance(ctx, "INTAKE_OPEN")
    return ctx


class TestStackedDiscountRounding:
    """Base 5500 (REGULAR tier), submitter with both flags: the pinned
    per-step rounding decides the final cent."""

    def _checkout(self, api):
        ctx = _open_ctx()
        submitter = st_submitter({
            "legal_name": "Stu Member", "email": "sm@example.com",
            "is_student": True, "is_member": True,
        })
        film = st_film(ctx, submitter, {
            "title": "Half Cent", "premiere_status": "NONE",
            "format": "PRORES_4444", "runtime_minutes": 12,
        }, pay=False)
        set_clock("2026-08-20T00:00:00Z")  # after early, before regular
        resp = api.checkout_submission(
            film["id"], make_filmmaker_headers(submitter["id"])
        )
        return validate_success(resp, 201)

    def test_stacked_discount_breakdown(self, api):
        """PRD §3.2: "Consider a base of 5500 cents with both flags set: the
        student discount is one quarter of 5500, exactly 1375; the member
        discount is one tenth of the remaining 4125, which is 412.50 and
        rounds half up to 413; the amount due is 5500 minus 1375 minus 413,
        which is 3712 cents."

        Design: Difficulty/combinatorial_formula/stacked_discount_rounding_order
        """
        payment = self._checkout(api)
        assert payment["tier_applied"] == "REGULAR"
        assert payment["base_fee_cents"] == 5500
        assert payment["student_discount_applied"] is True
        assert payment["member_discount_applied"] is True
        assert payment["student_discount_cents"] == 1375
        assert payment["member_discount_cents"] == 413
        assert payment["amount_cents"] == 3712

    def test_stacked_discount_not_single_step_rate(self, api):
        """PRD §3.2: "Computing the member discount as a single combined rate
        against the student-discounted base would yield 3713 cents and is
        forbidden — each discount is rounded individually before subtraction."

        Design: Difficulty/combinatorial_formula/stacked_discount_rounding_order
        """
        payment = self._checkout(api)
        assert payment["amount_cents"] == 3712
        assert payment["amount_cents"] != 3713, (
            "single-step stacked multiplication is forbidden; per-step "
            "round-half-up yields 3712"
        )
        assert payment["amount_cents"] == (
            payment["base_fee_cents"]
            - payment["student_discount_cents"]
            - payment["member_discount_cents"]
        )


class TestFeeTierBoundary:
    """NARRATIVE_FEATURE fees 9000/12000/15000; checkout exactly at the early
    deadline vs one second later."""

    CONFIG = {
        "min_runtime_minutes": 70,
        "max_runtime_minutes": 120, "premiere_requirement": "US_REQUIRED",
        "early_fee_cents": 9000, "regular_fee_cents": 12000,
        "late_fee_cents": 15000, "screener_count_required": 3,
    }

    def _open_feature_ctx(self):
        ctx = st_edition(config_over=self.CONFIG, category="NARRATIVE_FEATURE")
        st_advance(ctx, "INTAKE_OPEN")
        return ctx

    def test_checkout_at_exact_early_deadline_is_early(self, api):
        """PRD §3.2: "when the clock reads at or before `early_deadline_at`
        the `EARLY` tier applies" — the boundary instant is inclusive.

        Design: Difficulty/boundary_precision_check/fee_tier_at_exact_early_deadline
        """
        ctx = self._open_feature_ctx()
        submitter = st_submitter()
        film = st_film(ctx, submitter, {
            "title": "Tier A", "category": "NARRATIVE_FEATURE",
            "runtime_minutes": 90,
        }, pay=False)
        set_clock("2026-08-15T00:00:00Z")  # exactly early_deadline_at
        payment = validate_success(api.checkout_submission(
            film["id"], make_filmmaker_headers(submitter["id"]),
        ), 201)
        assert payment["tier_applied"] == "EARLY"
        assert payment["amount_cents"] == 9000
        assert payment["base_fee_cents"] == 9000

    def test_checkout_one_second_past_early_deadline_is_regular(self, api):
        """PRD §3.2: "when it reads after `early_deadline_at` and at or before
        `regular_deadline_at` the `REGULAR` tier applies".

        Design: Difficulty/boundary_precision_check/fee_tier_at_exact_early_deadline
        """
        ctx = self._open_feature_ctx()
        submitter = st_submitter()
        film = st_film(ctx, submitter, {
            "title": "Tier B", "category": "NARRATIVE_FEATURE",
            "runtime_minutes": 90,
        }, pay=False)
        set_clock("2026-08-15T00:00:01Z")  # one second past
        payment = validate_success(api.checkout_submission(
            film["id"], make_filmmaker_headers(submitter["id"]),
        ), 201)
        assert payment["tier_applied"] == "REGULAR"
        assert payment["amount_cents"] == 12000


class TestCheckoutIdempotence:
    def test_checkout_returns_existing_initiated_payment(self, api, admin_headers):
        """PRD §3.2: "Payment begins at checkout, which creates a fee payment
        for a `DRAFT` submission — or, if an `INITIATED` payment already
        exists for it, returns that same payment unchanged."

        Design: Corner/endpoints/checkout_returns_existing_initiated_payment
        """
        ctx = _open_ctx()
        submitter = st_submitter()
        film = st_film(ctx, submitter, {"title": "Twice"}, pay=False)
        headers = make_filmmaker_headers(submitter["id"])

        first = validate_success(api.checkout_submission(film["id"], headers), 201)
        assert first["tier_applied"] == "EARLY"
        assert first["amount_cents"] == 4000
        assert first["status"] == "INITIATED"

        set_clock("2026-08-20T00:00:00Z")  # now inside the REGULAR window
        second = validate_success(api.checkout_submission(film["id"], headers), 201)
        assert second["id"] == first["id"]
        assert second["amount_cents"] == first["amount_cents"] == 4000
        assert second["tier_applied"] == "EARLY", (
            "the open payment is returned unchanged even though the clock now "
            "reads in the REGULAR window"
        )

        payments = validate_success(api.list_fee_payments(
            admin_headers, params={"submission_id": film["id"]},
        ))
        assert len(payments) == 1, "exactly one payment row may exist"


class TestWithdrawRefund:
    def test_withdraw_half_refund_odd_cent(self, api, admin_headers):
        """PRD §3.2: "When a `SUCCEEDED` payment exists and no screening slot
        ever reached `HELD`, `CONFIRMED`, or `PLAYED` for the film's slate
        entry, the system auto-refunds half of `amount_cents`, rounded half up
        to whole cents — an amount of 6075 cents refunds 3038 — setting
        `refunded_amount_cents`, moving the payment to `PARTIALLY_REFUNDED`,
        the `payment_status` to `PARTIALLY_REFUNDED`, and recomputing the
        edition's `total_refunded_cents`."

        Design: Corner/calculations/withdraw_half_refund_odd_cent
        """
        ctx = fx_invited(
            films=[{
                "title": "Odd Cent",
                "scores": [("STAFF", 8), ("STAFF", 9), ("STAFF", 9)],
                "submission_over": {"runtime_minutes": 90,
                                    "production_company": "Penny"},
                "submitter_over": {"is_student": True, "is_member": True},
            }],
            category="NARRATIVE_FEATURE",
            config_over={
                "min_runtime_minutes": 70, "max_runtime_minutes": 120,
                "premiere_requirement": "US_REQUIRED",
                "early_fee_cents": 9000, "regular_fee_cents": 12000,
                "late_fee_cents": 15000, "screener_count_required": 3,
            },
            section="US_DRAMATIC", capacity_slots=1,
        )
        spec = ctx["films"][0]
        payment = ctx["payments"][spec["film"]["id"]]
        assert payment["amount_cents"] == 6075  # 9000 - 2250 - 675 (EARLY tier)

        withdrawn = validate_success(api.withdraw_submission(
            spec["film"]["id"], make_filmmaker_headers(spec["submitter"]["id"]),
        ))
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["payment_status"] == "PARTIALLY_REFUNDED"

        payment_after = validate_success(
            api.get_fee_payment(payment["id"], admin_headers)
        )
        assert payment_after["status"] == "PARTIALLY_REFUNDED"
        assert payment_after["refunded_amount_cents"] == 3038, (
            "round_half_up(6075 * 0.50) rounds the half cent up to 3038"
        )

        edition = validate_success(
            api.get_edition(ctx["edition"]["id"], admin_headers)
        )
        assert edition["total_refunded_cents"] == 3038


class TestAdminRefund:
    def _two_paid_films(self, api):
        ctx = _open_ctx()
        submitter = st_submitter()
        film_a = st_film(ctx, submitter, {"title": "Refund A"})
        film_b = st_film(ctx, submitter, {"title": "Refund B"})
        return ctx, submitter, film_a, film_b

    def test_admin_full_refund_cooling_window_boundary(self, api, admin_headers):
        """PRD §3.2: "the logical clock must read no later than 48 hours after
        `paid_at`, beyond which the request fails with
        `ERR_REFUND_WINDOW_CLOSED`"; a granted refund "moves the payment to
        `REFUNDED`, sets `refunded_amount_cents` to the full `amount_cents`".

        Design: Corner/calculations/admin_full_refund_cooling_window_boundary
        """
        ctx, submitter, film_a, film_b = self._two_paid_films(api)
        pay_a = ctx["payments"][film_a["id"]]
        pay_b = ctx["payments"][film_b["id"]]
        # paid_at == default clock 2026-08-01T00:00:00Z for both payments.
        set_clock("2026-08-03T00:00:00Z")  # exactly paid_at + 48h (inclusive)
        refunded = validate_success(
            api.refund_payment(pay_a["id"], "duplicate", admin_headers)
        )
        assert refunded["status"] == "REFUNDED"
        assert refunded["refunded_amount_cents"] == 4000  # EARLY short fee

        set_clock("2026-08-03T00:00:01Z")  # one second beyond the window
        closed = api.refund_payment(pay_b["id"], "duplicate", admin_headers)
        validate_error(closed, ApiErrorId.ERR_REFUND_WINDOW_CLOSED.value)

    def test_refund_guards_payment_and_submission_state(self, api, admin_headers):
        """PRD §3.2: "The payment must be `SUCCEEDED` — any other status
        yields `ERR_PAYMENT_NOT_REFUNDABLE` — ... and the submission must
        still be `SUBMITTED`, failing with `ERR_REFUND_NOT_ALLOWED` in any
        other status."

        Design: Corner/calculations/refund_guards_payment_and_submission_state
        """
        ctx = _open_ctx()
        submitter = st_submitter()
        film_a = st_film(ctx, submitter, {"title": "Refund A"})
        st_rule(ctx, film_a["id"], "ELIGIBLE")  # no longer SUBMITTED
        pay_a = ctx["payments"][film_a["id"]]

        film_b = st_film(ctx, submitter, {"title": "Refund B"}, pay=False)
        pay_b = validate_success(api.checkout_submission(
            film_b["id"], make_filmmaker_headers(submitter["id"]),
        ), 201)  # stays INITIATED

        not_allowed = api.refund_payment(pay_a["id"], "changed mind", admin_headers)
        validate_error(not_allowed, ApiErrorId.ERR_REFUND_NOT_ALLOWED.value)

        not_refundable = api.refund_payment(pay_b["id"], "changed mind", admin_headers)
        validate_error(not_refundable, ApiErrorId.ERR_PAYMENT_NOT_REFUNDABLE.value)
