"""Late-fee thresholds, invoice issue/void settlement rules, payments, rate
overlap, and billing OCC/RBAC checks."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    create_rate_schedule_payload, create_invoice_generate_payload,
    create_payment_payload, create_home, create_licensed_home, create_applicant,
    create_resident, setup_admitted_resident, setup_draft_invoice,
    generate_invoice_for, publish_rate_schedule, record_payment, set_clock,
    fresh_resident, fresh_invoice, add_caregiver, make_caregiver_headers,
    TEST_USERS,
)

PROVIDER = TEST_USERS["provider_headers"]
NURSE = TEST_USERS["nurse_headers"]

PP_RATE = {"payer_type": "PRIVATE_PAY", "room_and_board_daily_cents": 12000,
           "care_low_daily_cents": 3000, "care_medium_daily_cents": 6000,
           "care_high_daily_cents": 9000, "effective_from": "2026-06-01"}
MC_RATE = {"payer_type": "MEDICAID", "room_and_board_daily_cents": 12000,
           "care_low_daily_cents": 3000, "care_medium_daily_cents": 6000,
           "care_high_daily_cents": 9000, "effective_from": "2026-06-01"}


class TestLateFeeThresholds:
    def test_late_fee_min_clamp_applies(self, api):
        """PRD §3.8: "The late fee is evaluated at this exact moment against the
        logical clock: when the home-local current date is strictly after `due_date`,
        the fee is five percent of `subtotal_cents`, rounded half-up and then clamped
        to no less than 2500 cents and no more than 15000 cents; issuing exactly on
        `due_date` incurs no fee at all."

        Design: Corner/calculations/late_fee_min_clamp_applies
        """
        ctx = setup_draft_invoice(
            period_start="2026-06-01", period_end="2026-06-02",
            due_date="2026-06-05", rates=[dict(PP_RATE)],
            payer_type="PRIVATE_PAY", nursing_hours_per_week=4,
            adl_dependency_score=2, admission_date="2026-06-01",
            complete_clock="2026-06-01T14:00:00Z")
        assert ctx["invoice"]["subtotal_cents"] == 15000
        set_clock("2026-06-07T00:00:00Z")  # home-local date 2026-06-06 > due
        issued = validate_success(api.issue_invoice(ctx["invoice"]["id"], PROVIDER),
                                  200)
        assert issued["late_fee_cents"] == 2500, \
            f"raw 5% = 750 must clamp up to the 2500 floor, got {issued['late_fee_cents']}"
        assert issued["total_cents"] == 17500
        assert issued["status"] == "ISSUED"

    def test_late_fee_max_clamp_applies(self, api):
        """PRD §3.8: "The late fee is evaluated at this exact moment against the
        logical clock: when the home-local current date is strictly after `due_date`,
        the fee is five percent of `subtotal_cents`, rounded half-up and then clamped
        to no less than 2500 cents and no more than 15000 cents; issuing exactly on
        `due_date` incurs no fee at all."

        Design: Corner/calculations/late_fee_max_clamp_applies
        """
        high_rate = dict(PP_RATE, room_and_board_daily_cents=11000)
        ctx = setup_draft_invoice(
            period_start="2026-06-01", period_end="2026-06-21",
            due_date="2026-06-25", rates=[high_rate],
            payer_type="PRIVATE_PAY", nursing_hours_per_week=0,
            adl_dependency_score=5, admission_date="2026-06-01",
            complete_clock="2026-06-01T14:00:00Z")
        assert ctx["invoice"]["subtotal_cents"] == 400000, \
            "20 projected days x (11000 + 9000 HIGH)"
        set_clock("2026-06-26T12:00:00Z")  # home-local date 2026-06-26 > due
        issued = validate_success(api.issue_invoice(ctx["invoice"]["id"], PROVIDER),
                                  200)
        assert issued["late_fee_cents"] == 15000, \
            f"raw 5% = 20000 must clamp down to the 15000 ceiling, got {issued['late_fee_cents']}"
        assert issued["total_cents"] == 415000

    def test_late_fee_not_applied_on_due_date(self, api):
        """PRD §3.8: "The late fee is evaluated at this exact moment against the
        logical clock: when the home-local current date is strictly after `due_date`,
        the fee is five percent of `subtotal_cents`, rounded half-up and then clamped
        to no less than 2500 cents and no more than 15000 cents; issuing exactly on
        `due_date` incurs no fee at all."

        Design: Corner/cross_cutting_layers/late_fee_not_applied_on_due_date
        """
        ctx = setup_draft_invoice(
            period_start="2026-06-01", period_end="2026-06-02",
            due_date="2026-06-05", rates=[dict(PP_RATE)],
            payer_type="PRIVATE_PAY", nursing_hours_per_week=4,
            adl_dependency_score=2, admission_date="2026-06-01",
            complete_clock="2026-06-01T14:00:00Z")
        set_clock("2026-06-05T20:00:00Z")  # home-local date 2026-06-05 == due
        issued = validate_success(api.issue_invoice(ctx["invoice"]["id"], PROVIDER),
                                  200)
        assert issued["late_fee_cents"] == 0, \
            "issue on due_date exactly is not late (strictly-greater semantics)"
        assert issued["total_cents"] == 15000
        assert issued["status"] == "ISSUED"


class TestAcuityBandBoundary:
    def test_medicaid_high_band_via_adl_boundary(self, api):
        """PRD §3.7: "The acuity band itself comes from two assessment inputs: `LOW`
        when `adl_dependency_score` is at most two and `nursing_hours_per_week` is
        below five; `HIGH` when `adl_dependency_score` is at least five or
        `nursing_hours_per_week` is at least fifteen; `MEDIUM` otherwise."
        PRD §3.7: "A `MEDICAID` day line combines the same room-and-board floor and
        band add-on with a nursing component: the weekly nursing cost is
        `nursing_hours_per_week` times 1500 cents, capped at 9000 cents per week;
        that capped weekly amount is divided by seven to prorate it per day and
        truncated to whole cents; and the resulting daily rate is rounded half-up to
        whole cents."

        Design: Corner/calculations/medicaid_high_band_via_adl_boundary
        """
        ctx = setup_admitted_resident(
            payer_type="MEDICAID", nursing_hours_per_week=0, adl_dependency_score=5,
            medicaid_certified=True, rates=[dict(MC_RATE)],
            admission_date="2026-06-01", complete_clock="2026-06-01T14:00:00Z")
        set_clock("2026-06-02T00:00:00Z")
        invoice = generate_invoice_for(ctx["resident"]["id"],
                                       period_start="2026-06-01",
                                       period_end="2026-06-02",
                                       due_date="2026-06-20")
        assert invoice["subtotal_cents"] == 21000, (
            f"1 day x (12000 + 9000 HIGH + trunc(0/7)=0) = 21000, got "
            f"{invoice['subtotal_cents']}")
        assert invoice["payer_type_snapshot"] == "MEDICAID"


class TestInvoiceIssueRules:
    def test_issue_requires_line_items(self, api):
        """PRD §3.8: "Issuing by a `Provider` moves a `DRAFT` invoice to `ISSUED` and
        requires the invoice to have at least one line item."
        PRD §3.7: "An occupied day is a home-local calendar date within the half-open
        billing period — `period_start` inclusive, `period_end` exclusive — on which
        a bed-stay exists: the resident's `admitted_at` falls at or before the end of
        that day, and either `discharged_at` is null or it falls after the start of
        that day."

        Design: Corner/state_machines/invoice_issue_requires_line_items
        """
        ctx = setup_draft_invoice(
            period_start="2026-06-01", period_end="2026-06-05",
            due_date="2026-06-20", rates=[dict(PP_RATE)],
            payer_type="PRIVATE_PAY", nursing_hours_per_week=4,
            adl_dependency_score=2, admission_date="2026-06-10",
            complete_clock="2026-06-10T14:00:00Z")
        assert ctx["invoice"]["subtotal_cents"] == 0, \
            "every window day precedes the admission, so no day is occupied"
        assert ctx["invoice"]["line_items"] == []
        res = api.issue_invoice(ctx["invoice"]["id"], PROVIDER)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_paid_invoice_cannot_be_voided(self, api):
        """PRD §3.8: "Voiding moves `DRAFT` → `VOID` freely, or `ISSUED` → `VOID`
        only while no payments have been recorded against the invoice; `VOID` and
        `PAID` are both terminal."
        PRD §2.9: "State-machine legality — the target resource is in a from-state
        that permits the transition and is not terminally locked; failure yields
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/invoice_terminal_paid_lockdown
        """
        ctx = setup_draft_invoice(
            period_start="2026-06-01", period_end="2026-06-02",
            due_date="2026-06-20", rates=[dict(PP_RATE)],
            payer_type="PRIVATE_PAY", nursing_hours_per_week=4,
            adl_dependency_score=2, admission_date="2026-06-01",
            complete_clock="2026-06-01T14:00:00Z")
        set_clock("2026-06-03T00:00:00Z")  # on time: no late fee
        issued = validate_success(api.issue_invoice(ctx["invoice"]["id"], PROVIDER),
                                  200)
        assert issued["total_cents"] == 15000
        record_payment(ctx["resident"]["id"], ctx["invoice"]["id"], 15000,
                       method="CASH")
        assert fresh_invoice(ctx["invoice"]["id"])["status"] == "PAID"
        res = api.void_invoice(ctx["invoice"]["id"], PROVIDER)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_generate_without_covering_rate_rejected(self, api):
        """PRD §3.7: "If no schedule covers an occupied day, generation fails with
        `ERR_RATE_NOT_FOUND`."

        Design: Corner/errors/err_rate_not_found_triggered
        """
        ctx = setup_admitted_resident(
            payer_type="PRIVATE_PAY", nursing_hours_per_week=4,
            adl_dependency_score=2, admission_date="2026-06-01",
            complete_clock="2026-06-01T14:00:00Z")
        res = api.generate_invoice(
            ctx["resident"]["id"],
            create_invoice_generate_payload(
                fresh_resident(ctx["resident"]["id"])["version"],
                period_start="2026-06-01", period_end="2026-06-03",
                due_date="2026-06-20"),
            PROVIDER)
        validate_error(res, ApiErrorId.ERR_RATE_NOT_FOUND, expected_status=422)

    def test_occ_stale_resident_version_rejected(self, api):
        """PRD §2.7: "A `POST /api/residents/{id}/invoices/generate` request must
        carry `expected_resident_version` equal to the resident's current `version`.
        A payer-type change or a discharge landing in between changes which rate
        schedule and which occupancy window apply, so the stale generation is refused
        with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_invoice_generate_stale_resident_version
        """
        ctx = setup_admitted_resident(
            payer_type="PRIVATE_PAY", nursing_hours_per_week=4,
            adl_dependency_score=2, rates=[dict(PP_RATE)],
            admission_date="2026-06-01", complete_clock="2026-06-01T14:00:00Z")
        stale_version = fresh_resident(ctx["resident"]["id"])["version"]
        first = api.generate_invoice(
            ctx["resident"]["id"],
            create_invoice_generate_payload(stale_version,
                                            period_start="2026-06-01",
                                            period_end="2026-06-02",
                                            due_date="2026-06-20"),
            PROVIDER)
        validate_success(first, 201)
        res = api.generate_invoice(
            ctx["resident"]["id"],
            create_invoice_generate_payload(stale_version,
                                            period_start="2026-06-02",
                                            period_end="2026-06-03",
                                            due_date="2026-06-20"),
            PROVIDER)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    def test_caregiver_cannot_generate_invoice(self, api):
        """PRD §2.1: "A request that is authenticated but whose role is not permitted
        on the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §2.9: "Authorization — the role is permitted on the endpoint; failure
        yields `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/caregiver_cannot_generate_invoice
        """
        home = create_home(name="RBAC Cg Inv", licensed_bed_capacity=4)
        caregiver = add_caregiver(home["id"], full_name="Cg RI")
        resident = create_resident(home["id"], full_name="Res RI")
        res = api.generate_invoice(
            resident["id"],
            create_invoice_generate_payload(resident["version"],
                                            period_start="2026-06-01",
                                            period_end="2026-06-11",
                                            due_date="2026-06-20"),
            make_caregiver_headers(caregiver["id"]))
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


class TestPaymentOnVoidInvoice:
    def _setup_void_invoice(self, api):
        ctx = setup_draft_invoice(
            period_start="2026-06-01", period_end="2026-06-11",
            due_date="2026-06-20", rates=[dict(PP_RATE)],
            payer_type="PRIVATE_PAY", nursing_hours_per_week=4,
            adl_dependency_score=2, admission_date="2026-06-01",
            complete_clock="2026-06-01T14:00:00Z")
        validate_success(api.void_invoice(ctx["invoice"]["id"], PROVIDER), 200)
        return ctx

    def test_payment_on_void_invoice_returns_invalid_state(self, api):
        """PRD §2.9: "Every request passes through a fixed, globally ordered
        validation pipeline, and the first failing check determines the error
        returned."
        PRD §3.8: "Voiding moves `DRAFT` → `VOID` freely, or `ISSUED` → `VOID` only
        while no payments have been recorded against the invoice; `VOID` and `PAID`
        are both terminal."
        PRD §2.9: "State-machine legality — the target resource is in a from-state
        that permits the transition and is not terminally locked; failure yields
        `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/payment_on_void_invoice_state_beats_fiscal
        """
        ctx = self._setup_void_invoice(api)
        res = api.create_payment(
            create_payment_payload(ctx["resident"]["id"], ctx["invoice"]["id"],
                                   999999, method="CASH"),
            PROVIDER)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_void_invoice_records_no_payment(self, api):
        """PRD §3.8: "Voiding moves `DRAFT` → `VOID` freely, or `ISSUED` → `VOID`
        only while no payments have been recorded against the invoice; `VOID` and
        `PAID` are both terminal."

        Design: Difficulty/priority_pair_validation_conflict/payment_on_void_invoice_state_beats_fiscal
        """
        ctx = self._setup_void_invoice(api)
        api.create_payment(
            create_payment_payload(ctx["resident"]["id"], ctx["invoice"]["id"],
                                   999999, method="CASH"),
            PROVIDER)
        assert fresh_invoice(ctx["invoice"]["id"])["status"] == "VOID"
        data, meta = validate_paginated(api.list_payments(
            PROVIDER, params={"invoice_id": ctx["invoice"]["id"]}))
        assert meta["total_count"] == 0, \
            "a rejected payment must not persist a payment row"


class TestPartialPaymentInvariant:
    def _setup_issued_invoice_with_late_fee(self, api):
        ctx = setup_draft_invoice(
            period_start="2026-06-01", period_end="2026-06-11",
            due_date="2026-06-20", rates=[dict(PP_RATE)],
            payer_type="PRIVATE_PAY", nursing_hours_per_week=4,
            adl_dependency_score=2, admission_date="2026-06-01",
            complete_clock="2026-06-01T14:00:00Z")
        assert ctx["invoice"]["subtotal_cents"] == 150000
        # Home-local date 2026-06-21 is strictly after due_date 2026-06-20.
        set_clock("2026-06-22T00:00:00Z")
        issued = validate_success(api.issue_invoice(ctx["invoice"]["id"], PROVIDER),
                                  200)
        assert issued["late_fee_cents"] == 7500, \
            "5% of 150000, inside the clamps"
        assert issued["total_cents"] == 157500
        return ctx

    def test_overpay_attempt_rejected_without_disturbing_balance(self, api):
        """PRD §3.8: "The amount must be positive and must not exceed the invoice's
        outstanding balance, else the payment is rejected with `ERR_OVERPAYMENT`."

        Design: Difficulty/compensating_invariant/partial_payments_conserve_invoice_total
        """
        ctx = self._setup_issued_invoice_with_late_fee(api)
        record_payment(ctx["resident"]["id"], ctx["invoice"]["id"], 100000,
                       method="CHECK")
        assert fresh_invoice(ctx["invoice"]["id"])["status"] == "PARTIALLY_PAID"
        res = api.create_payment(
            create_payment_payload(ctx["resident"]["id"], ctx["invoice"]["id"],
                                   57501, method="CHECK"),
            PROVIDER)
        validate_error(res, ApiErrorId.ERR_OVERPAYMENT, expected_status=422)

    def test_exact_remainder_completes_payment_and_conserves_total(self, api):
        """PRD §3.8: "A payment below the outstanding balance moves the invoice
        `ISSUED` → `PARTIALLY_PAID`; a payment exactly equal to the outstanding
        balance moves it `ISSUED` → `PAID` directly; and once cumulative payments
        reach the `total_cents`, a `PARTIALLY_PAID` invoice becomes `PAID`."

        Design: Difficulty/compensating_invariant/partial_payments_conserve_invoice_total
        """
        ctx = self._setup_issued_invoice_with_late_fee(api)
        record_payment(ctx["resident"]["id"], ctx["invoice"]["id"], 100000,
                       method="CHECK")
        record_payment(ctx["resident"]["id"], ctx["invoice"]["id"], 57500,
                       method="ACH")
        invoice = fresh_invoice(ctx["invoice"]["id"])
        assert invoice["status"] == "PAID"
        data, meta = validate_paginated(api.list_payments(
            PROVIDER, params={"invoice_id": ctx["invoice"]["id"]}))
        total_paid = sum(p["amount_cents"] for p in data)
        assert total_paid == 157500 == invoice["total_cents"], (
            "sum of payments plus zero outstanding must equal total_cents at every "
            "step")


class TestPaymentImmediateConsistency:
    def test_payment_effect_immediately_visible_on_invoice_read(self, api):
        """PRD §1: "First, consistency is immediate and cascading: a single decision
        — a home closure, a discharge, a substantiated citation — propagates through
        beds, admissions, medication orders, shifts, and derived counters in one
        step, and every propagation is recorded."
        PRD §3.8: "A payment below the outstanding balance moves the invoice `ISSUED`
        → `PARTIALLY_PAID`; a payment exactly equal to the outstanding balance moves
        it `ISSUED` → `PAID` directly; and once cumulative payments reach the
        `total_cents`, a `PARTIALLY_PAID` invoice becomes `PAID`."

        Design: Corner/consistency_model/payment_effect_immediately_visible_on_invoice_read
        """
        ctx = setup_draft_invoice(
            period_start="2026-06-01", period_end="2026-06-02",
            due_date="2026-06-20", rates=[dict(PP_RATE)],
            payer_type="PRIVATE_PAY", nursing_hours_per_week=4,
            adl_dependency_score=2, admission_date="2026-06-01",
            complete_clock="2026-06-01T14:00:00Z")
        set_clock("2026-06-03T00:00:00Z")
        issued = validate_success(api.issue_invoice(ctx["invoice"]["id"], PROVIDER),
                                  200)
        pre_payment_version = issued["version"]
        payment = validate_success(api.create_payment(
            create_payment_payload(ctx["resident"]["id"], ctx["invoice"]["id"],
                                   5000, method="ACH"),
            PROVIDER), 201)
        invoice_after = fresh_invoice(ctx["invoice"]["id"])
        assert invoice_after["status"] == "PARTIALLY_PAID", \
            "the very next read must already show the payment effect"
        assert invoice_after["version"] > pre_payment_version, \
            "the payment mutation must increment the invoice version"


class TestRateScheduleOverlap:
    def test_adjacent_schedule_accepted(self, api):
        """PRD §3.7: "A new schedule whose effective window intersects an existing
        schedule for the same home and the same `payer_type` — a half-open
        intersection — is rejected with `ERR_RATE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/rate_schedule_overlap_adjacency_allowed_intersection_rejected
        """
        ctx = create_licensed_home(name="Maple2 AFH", bed_label="1A")
        publish_rate_schedule(
            ctx["home"]["id"], payer_type="MEDICAID", effective_from="2026-06-01",
            effective_to="2026-06-15")
        adjacent = api.create_rate_schedule(
            ctx["home"]["id"],
            create_rate_schedule_payload(
                payer_type="MEDICAID", room_and_board_daily_cents=12500,
                care_low_daily_cents=3100, care_medium_daily_cents=6200,
                care_high_daily_cents=9200, effective_from="2026-06-15"),
            PROVIDER)
        schedule = validate_success(adjacent, 201)
        assert schedule["effective_from"] == "2026-06-15", (
            "a window starting exactly at the prior window's exclusive end touches "
            "but does not intersect it")

    def test_interior_intersection_rejected(self, api):
        """PRD §3.7: "A new schedule whose effective window intersects an existing
        schedule for the same home and the same `payer_type` — a half-open
        intersection — is rejected with `ERR_RATE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/rate_schedule_overlap_adjacency_allowed_intersection_rejected
        """
        ctx = create_licensed_home(name="Maple2 AFH", bed_label="1A")
        publish_rate_schedule(
            ctx["home"]["id"], payer_type="MEDICAID", effective_from="2026-06-01",
            effective_to="2026-06-15")
        publish_rate_schedule(
            ctx["home"]["id"], payer_type="MEDICAID",
            room_and_board_daily_cents=12500, care_low_daily_cents=3100,
            care_medium_daily_cents=6200, care_high_daily_cents=9200,
            effective_from="2026-06-15")
        res = api.create_rate_schedule(
            ctx["home"]["id"],
            create_rate_schedule_payload(
                payer_type="MEDICAID", room_and_board_daily_cents=13000,
                care_low_daily_cents=3200, care_medium_daily_cents=6300,
                care_high_daily_cents=9300, effective_from="2026-06-14",
                effective_to="2026-06-20"),
            PROVIDER)
        validate_error(res, ApiErrorId.ERR_RATE_OVERLAP, expected_status=409)
