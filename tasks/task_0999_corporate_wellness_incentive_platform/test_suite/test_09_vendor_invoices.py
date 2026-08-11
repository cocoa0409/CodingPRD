"""Vendor invoicing: proration and rounding, SoD/fiscal guards, lifecycle (PRD §3.8)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_enrollment,
    create_employee,
    create_enrollment,
    create_invoice,
    create_invoice_adjustment_payload,
    invoice_by_id,
    make_platform_admin_headers,
    make_vendor_manager_headers,
    set_clock,
    setup_active_enrollment,
    setup_cohort,
    setup_submitted_invoice,
    submit_invoice,
    validate_error,
    validate_success,
)

BA = TEST_USERS["benefits_admin_headers"]


class TestMemberMonthRounding:
    """Difficulty instance: each MEMBER_MONTH line is rounded half-up to integer
    cents BEFORE summation; sum-then-round is explicitly rejected."""

    def _setup_two_member_invoice(self, api):
        ctx = setup_cohort(0)  # employer + ACTIVE program only
        set_clock("2026-05-17T09:00:00Z")
        for n in (1, 2):
            employee = create_employee(ctx["employer"]["id"], n=n)
            enrollment = create_enrollment(ctx["program"]["id"], employee["id"])
            accept_enrollment(enrollment["id"], employee["id"])
        invoice = create_invoice(ctx["program"]["id"])
        return ctx, invoice

    def test_member_month_lines_rounded_per_line(self, api):
        """PRD §3.8: "When the span is positive, the line amount is the employer's
        `pmpm_fee_cents` multiplied by the member-day count and divided by the
        period length, rounded half-up to whole cents, and the line is emitted as
        `MEMBER_MONTH` with `ref_id` naming the enrollment."
        PRD §2.9: "every member-month line is individually rounded half-up to
        integer cents before any summation, and `total_cents` is the exact sum of
        the already-rounded line amounts. The alternative — summing unrounded
        prorations and rounding once at the end — is explicitly rejected and yields
        different cents."

        Design: Difficulty/combinatorial_formula/invoice_member_month_per_line_rounding
        """
        _ctx, invoice = self._setup_two_member_invoice(api)
        member_lines = [l for l in invoice["line_items"] if l["line_type"] == "MEMBER_MONTH"]
        assert len(member_lines) == 2, "one MEMBER_MONTH line per enrolled member"
        for line in member_lines:
            assert line["amount_cents"] == 4839, (
                "round_half_up(10000 * 15 / 31) == 4839 per line"
            )
        assert invoice["total_cents"] == 9678, (
            "per-line rounding yields 9678; sum-then-round would yield 9677"
        )

    def test_invoice_without_sessions_has_no_coaching_lines(self, api):
        """PRD §3.8: "for each CoachingReferral of the program's enrollments, the
        platform counts the `session_dates` falling within the inclusive period,
        and when that count is positive emits a `COACHING_SESSION` line for the
        count times the employer's `coaching_session_fee_cents`, with `ref_id`
        naming the referral."

        Design: Difficulty/combinatorial_formula/invoice_member_month_per_line_rounding
        """
        ctx, invoice = self._setup_two_member_invoice(api)
        coaching_lines = [
            l for l in invoice["line_items"] if l["line_type"] == "COACHING_SESSION"
        ]
        assert coaching_lines == [], "no referrals exist, so no coaching lines"
        assert invoice["total_cents"] == sum(
            l["amount_cents"] for l in invoice["line_items"]
        ), "total_cents is the exact sum of rounded line amounts"


class TestInvoiceAdjustmentCompensation:
    """Difficulty instance: money conservation — total_cents is the exact sum of
    line_items; a +1200/-1200 ADJUSTMENT pair restores the pre-pair total."""

    def test_compensating_adjustment_lines_restore_total(self, api):
        """PRD §3.8: "While the invoice is `DRAFT`, the vendor may append a signed
        `ADJUSTMENT` line by supplying an `amount_cents` and a `note`; the total is
        re-summed and the invoice's `version` increments."
        PRD §2.9: "every member-month line is individually rounded half-up to
        integer cents before any summation, and `total_cents` is the exact sum of
        the already-rounded line amounts."

        Design: Difficulty/compensating_invariant/invoice_adjustment_compensation_invariant
        """
        ctx = setup_active_enrollment()
        invoice = create_invoice(ctx["program"]["id"])
        assert invoice["total_cents"] == 10000, "one full-month member line"

        validate_success(
            api.create_invoice_adjustment(
                invoice["id"], create_invoice_adjustment_payload(1200, "setup fee"),
                TEST_USERS["vendor_manager_headers"],
            ),
            201,
        )
        after_pair = validate_success(
            api.create_invoice_adjustment(
                invoice["id"], create_invoice_adjustment_payload(-1200, "reversal of setup fee"),
                TEST_USERS["vendor_manager_headers"],
            ),
            201,
        )

        assert after_pair["total_cents"] == 10000, (
            "+1200 then -1200 must restore the pre-pair total"
        )
        kinds = [l["line_type"] for l in after_pair["line_items"]]
        assert kinds.count("MEMBER_MONTH") == 1
        assert kinds.count("ADJUSTMENT") == 2
        adjustments = sorted(
            l["amount_cents"] for l in after_pair["line_items"]
            if l["line_type"] == "ADJUSTMENT"
        )
        assert adjustments == [-1200, 1200]

    def test_adjustments_do_not_change_invoice_state(self, api):
        """PRD §3.8: "While the invoice is `DRAFT`, the vendor may append a signed
        `ADJUSTMENT` line by supplying an `amount_cents` and a `note`; the total is
        re-summed and the invoice's `version` increments."
        PRD §2.4: "A system-managed integer that increments by exactly one with
        every modification to the resource."

        Design: Difficulty/compensating_invariant/invoice_adjustment_compensation_invariant
        """
        ctx = setup_active_enrollment()
        invoice = create_invoice(ctx["program"]["id"])
        created_version = invoice["version"]

        validate_success(
            api.create_invoice_adjustment(
                invoice["id"], create_invoice_adjustment_payload(1200, "setup fee"),
                TEST_USERS["vendor_manager_headers"],
            ),
            201,
        )
        after = validate_success(
            api.create_invoice_adjustment(
                invoice["id"], create_invoice_adjustment_payload(-1200, "reversal"),
                TEST_USERS["vendor_manager_headers"],
            ),
            201,
        )

        assert after["status"] == "DRAFT", "adjustments do not change invoice state"
        assert after["version"] == created_version + 2, (
            "each adjustment increments the invoice version by exactly one"
        )


class TestApproveGuards:
    """Difficulty instance: business_safety (SoD) outranks business_fiscal (limit)."""

    def test_sod_and_limit_violated_reports_sod(self, api):
        """PRD §2.6: "an invoice approval that violates both segregation of duties
        and the spending limit reports `ERR_SOD_VIOLATION`, because stage 7 is
        evaluated before stage 11."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_invoice_approve
        """
        ctx = setup_submitted_invoice(submitter="ops-user-1")
        invoice = ctx["invoice"]
        assert invoice["total_cents"] == 10000, "over the 5000 approval limit"

        res = api.approve_vendor_invoice(
            invoice["id"], {}, make_platform_admin_headers("ops-user-1")
        )
        validate_error(res, ApiErrorId.ERR_SOD_VIOLATION, expected_status=403)

    def test_sod_violation_isolated_from_limit(self, api):
        """PRD §2.11: "The operator who submits an invoice is recorded as its
        `submitted_by`, and the `PlatformAdmin` who approves it must be a different
        operator: when the approver's `X-User-ID` equals the invoice's
        `submitted_by`, the approval is rejected with `ERR_SOD_VIOLATION`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_invoice_approve
        """
        ctx = setup_cohort(0)  # employer + ACTIVE program
        set_clock("2026-05-17T09:00:00Z")
        employee = create_employee(ctx["employer"]["id"], n=1)
        enrollment = create_enrollment(ctx["program"]["id"], employee["id"])
        accept_enrollment(enrollment["id"], employee["id"])
        invoice = create_invoice(ctx["program"]["id"])
        assert invoice["total_cents"] == 4839, "under the 5000 approval limit"
        invoice = submit_invoice(invoice["id"], "ops-user-1")

        res = api.approve_vendor_invoice(
            invoice["id"], {}, make_platform_admin_headers("ops-user-1")
        )
        validate_error(res, ApiErrorId.ERR_SOD_VIOLATION, expected_status=403)

        listed = invoice_by_id(invoice["id"], ctx["program"]["id"])
        assert listed["status"] == "SUBMITTED", "rejected approval leaves the invoice SUBMITTED"


class TestInvoiceLifecycle:
    def test_invoice_pay_from_draft_rejected(self, api):
        """PRD §3.8: "An approved invoice is paid, moving from `APPROVED` to `PAID`,
        which is terminal."
        PRD §2.6: "The target resource is in a valid from-state for the requested
        transition; otherwise the state-family error applies — `ERR_INVALID_STATE`
        generically..."

        Design: Corner/state_machines/invoice_pay_from_draft_rejected
        """
        ctx = setup_active_enrollment()
        invoice = create_invoice(ctx["program"]["id"])
        assert invoice["status"] == "DRAFT"

        res = api.pay_vendor_invoice(invoice["id"], TEST_USERS["platform_admin_headers"])
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_invoice_approval_limit_enforced_without_override(self, api):
        """PRD §3.8: "a `total_cents` strictly greater than the employer's
        `invoice_approval_limit_cents` is rejected with `ERR_INVOICE_EXCEEDS_LIMIT`
        unless the approval explicitly carries `override_limit` set to true."

        Design: Corner/errors/invoice_approval_limit_enforced_without_override
        """
        ctx = setup_submitted_invoice(submitter="ops-user-1")
        invoice = ctx["invoice"]
        assert invoice["total_cents"] == 10000

        res = api.approve_vendor_invoice(
            invoice["id"], {}, make_platform_admin_headers("admin-9")
        )
        validate_error(res, ApiErrorId.ERR_INVOICE_EXCEEDS_LIMIT, expected_status=422)

        approved = validate_success(
            api.approve_vendor_invoice(
                invoice["id"], {"override_limit": True},
                make_platform_admin_headers("admin-9"),
            ),
            200,
        )
        assert approved["status"] == "APPROVED"

    def test_invoice_dispute_revise_cycle_clears_submitter(self, api):
        """PRD §3.8: "Alternatively, a `PlatformAdmin` may dispute a `SUBMITTED`
        invoice with an explanatory `note` (`SUBMITTED → DISPUTED`), and the vendor
        may then revise it (`DISPUTED → DRAFT`), which clears `submitted_by` to
        null and reopens the draft for adjustment and resubmission."

        Design: Corner/endpoints/invoice_dispute_revise_cycle_clears_submitter
        """
        ctx = setup_submitted_invoice(submitter="ops-user-1")
        invoice = ctx["invoice"]

        disputed = validate_success(
            api.dispute_vendor_invoice(
                invoice["id"], {"note": "member count looks high"},
                TEST_USERS["platform_admin_headers"],
            ),
            200,
        )
        assert disputed["status"] == "DISPUTED"

        revised = validate_success(
            api.revise_vendor_invoice(invoice["id"], TEST_USERS["vendor_manager_headers"]),
            200,
        )
        assert revised["status"] == "DRAFT"
        assert revised["submitted_by"] is None, "revise clears the recorded submitter"
        assert revised["total_cents"] == 10000, "lines unchanged through the cycle"

    def test_invoice_adjustment_on_submitted_rejected(self, api):
        """PRD §3.8: "Adjustments against a non-`DRAFT` invoice are rejected with
        `ERR_INVOICE_NOT_EDITABLE`."

        Design: Corner/errors/invoice_adjustment_on_submitted_rejected
        """
        ctx = setup_submitted_invoice(submitter="ops-user-1")
        invoice = ctx["invoice"]

        res = api.create_invoice_adjustment(
            invoice["id"], create_invoice_adjustment_payload(500, "late fee"),
            TEST_USERS["vendor_manager_headers"],
        )
        validate_error(res, ApiErrorId.ERR_INVOICE_NOT_EDITABLE, expected_status=409)

        listed = invoice_by_id(invoice["id"], ctx["program"]["id"])
        assert listed["total_cents"] == 10000, "rejected adjustment leaves the total unchanged"


class TestVendorManagerRoleExclusion:
    def test_vendor_manager_cannot_approve_invoice_forbidden(self, api):
        """PRD §2.11: "A `VendorManager` may draft, adjust, submit, and revise
        invoices but may never approve one."
        PRD §2.1: "Access to specific operations is further restricted by role; an
        attempt to perform an action outside of the caller's designated role is
        rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/vendor_manager_cannot_approve_invoice_forbidden
        """
        ctx = setup_submitted_invoice(submitter="ops-user-1")
        res = api.approve_vendor_invoice(
            ctx["invoice"]["id"], {"override_limit": True},
            make_vendor_manager_headers("ops-user-2"),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
