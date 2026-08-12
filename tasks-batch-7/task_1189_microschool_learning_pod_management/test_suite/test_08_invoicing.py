"""Invoicing claims: per-line-then-sum subtotal, tiered admin fee at the
enrollment-count boundary, and billing-period validity."""
from test_helpers import (
    ApiErrorId,
    create_invoice_payload,
    validate_error,
    validate_success,
    TEST_USERS,
)
from test_helpers.fixtures import (
    create_issued_invoice,
    enroll_seat,
    set_clock,
    setup_active_pod_with_enrolled_seats,
    setup_enrolled_seat,
    setup_family_student_seat,
    setup_pod_active,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPERATOR = TEST_USERS["pod_operator_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]

# Line items engineered so per-line rounding is observable:
#   round(1 * 100000) + round(3 * 3333) = 100000 + 9999 = 109999.
FEE_LINE_ITEMS = [
    {"description": "Tuition", "quantity": 1, "unit_amount_cents": 100000,
     "kind": "TUITION"},
    {"description": "Materials", "quantity": 3, "unit_amount_cents": 3333,
     "kind": "FEE"},
]
EXPECTED_SUBTOTAL = 109999


class TestTieredAdminFee:
    def test_admin_fee_at_tier_boundary_eight_enrolled(self, api):
        """PRD 3.7: "Second, `admin_fee_cents` is computed as a percentage
        of that subtotal, tiered by the pod's `enrolled_count` at the moment
        of issuance — not by the student's own seat count: four percent when
        the pod has at most eight enrolled seats, three percent from nine
        through sixteen, two percent from seventeen through twenty-four, and
        one and a half percent at twenty-five or more, with the fee itself
        rounded half up to a whole cent. Boundary counts belong to the
        higher-fee tier: exactly eight seats bills four percent, exactly
        sixteen bills three, exactly twenty-four bills two."
        PRD 3.7: "First, `subtotal_cents` is computed per line: each line's
        extended amount is its `quantity` multiplied by its
        `unit_amount_cents`, rounded half up to a whole cent, and the
        subtotal is the sum of those rounded line amounts."

        Design: Difficulty/combinatorial_formula/tiered_admin_fee_tiered_rates
        """
        set_clock("2026-08-15T00:00:00Z")
        ctx = setup_active_pod_with_enrolled_seats(num_seats=8, seat_capacity=12)
        pod = ctx["pod"]
        assert pod["enrolled_count"] == 8
        # A ninth seat stays RESERVED (uncounted); the invoice is issued on
        # an ENROLLED seat as PRD 3.7 requires ("Issuance is a PodOperator
        # action requiring the seat to be ENROLLED"), and prices against the
        # pod's enrolled_count of 8.
        family, student, seat = setup_family_student_seat(pod)
        enrolled_seat = ctx["seats"][0][2]
        inv = create_issued_invoice(
            pod["id"], enrolled_seat["id"], line_items=FEE_LINE_ITEMS,
        )
        assert inv["subtotal_cents"] == EXPECTED_SUBTOTAL, (
            f"per-line-then-sum subtotal must be 109999, got "
            f"{inv['subtotal_cents']}"
        )
        assert inv["admin_fee_cents"] == 4400, (
            f"at enrolled_count == 8 the 4% tier applies: expected 4400, got "
            f"{inv['admin_fee_cents']}"
        )
        assert inv["total_cents"] == EXPECTED_SUBTOTAL + 4400

    def test_admin_fee_drops_one_tier_at_nine_enrolled(self, api):
        """PRD 3.7: "Second, `admin_fee_cents` is computed as a percentage
        of that subtotal, tiered by the pod's `enrolled_count` at the moment
        of issuance — not by the student's own seat count: four percent when
        the pod has at most eight enrolled seats, three percent from nine
        through sixteen, two percent from seventeen through twenty-four, and
        one and a half percent at twenty-five or more, with the fee itself
        rounded half up to a whole cent. Boundary counts belong to the
        higher-fee tier: exactly eight seats bills four percent, exactly
        sixteen bills three, exactly twenty-four bills two."

        Design: Difficulty/combinatorial_formula/tiered_admin_fee_tiered_rates
        """
        set_clock("2026-08-15T00:00:00Z")
        ctx = setup_active_pod_with_enrolled_seats(num_seats=8, seat_capacity=12)
        pod = ctx["pod"]
        # Enroll a ninth seat; issuance now prices against enrolled_count=9.
        family, student, seat = setup_family_student_seat(pod)
        seat = enroll_seat(pod["id"], seat, family["id"])
        assert seat["seat_status"] == "ENROLLED"
        pod_now = validate_success(api.get_pod(pod["id"], OPERATOR))
        assert pod_now["enrolled_count"] == 9

        inv = create_issued_invoice(
            pod["id"], seat["id"], line_items=FEE_LINE_ITEMS,
        )
        assert inv["subtotal_cents"] == EXPECTED_SUBTOTAL
        assert inv["admin_fee_cents"] == 3300, (
            f"at enrolled_count == 9 the 3% tier applies: expected 3300, got "
            f"{inv['admin_fee_cents']}"
        )
        assert inv["total_cents"] == EXPECTED_SUBTOTAL + 3300

    def test_tiered_admin_fee_correct_result(self, api):
        """PRD 3.7: "Finally, `total_cents` is the subtotal plus the fee.
        This per-line-then-sum order is contractual: summing raw extended
        amounts and rounding once at the end produces different cents for
        fractional quantities and is not permitted."

        Design: Corner/calculations/tiered_admin_fee_correct_result
        """
        set_clock("2026-08-15T00:00:00Z")
        ctx = setup_active_pod_with_enrolled_seats(num_seats=8, seat_capacity=12)
        pod = ctx["pod"]
        assert pod["enrolled_count"] == 8
        # Issuance requires an ENROLLED seat (PRD 3.7).
        enrolled_seat = ctx["seats"][0][2]
        inv = create_issued_invoice(
            pod["id"], enrolled_seat["id"], line_items=FEE_LINE_ITEMS,
        )
        assert inv["subtotal_cents"] == 109999
        assert inv["admin_fee_cents"] == 4400


class TestInvoicePeriodValidity:
    def test_err_invalid_invoice_period_triggerable(self, api):
        """PRD 3.7: "A `PodOperator` drafts an invoice for a seat with a
        `billing_period_start`, a `billing_period_end` that must not precede
        it, a `due_date` that must not precede the period end — violations
        rejected as `ERR_INVALID_INVOICE_PERIOD` (HTTP 422) — and a
        `line_items` array whose entries each carry a `description`, a
        `quantity`, a `unit_amount_cents`, and a `kind` of `TUITION`, `FEE`,
        or `CREDIT`."

        Design: Corner/errors/err_invalid_invoice_period_triggerable
        """
        set_clock("2026-08-15T00:00:00Z")
        pod, *_ = setup_pod_active()
        family, student, seat = setup_enrolled_seat(pod)
        resp = api.create_invoice(
            pod["id"], seat["id"],
            create_invoice_payload(
                billing_period_start="2026-10-01",
                billing_period_end="2026-09-01",
                due_date="2026-10-15",
            ),
            OPERATOR,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_INVOICE_PERIOD,
                       expected_status=422)
