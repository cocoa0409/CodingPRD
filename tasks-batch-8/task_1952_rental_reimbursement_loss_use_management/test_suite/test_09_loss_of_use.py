"""Loss-of-use claims: eligibility, closed-interval semantics, payout variants,
documentation gating, ownership, and track independence."""
import pytest

from test_helpers import (
    ADJUSTER,
    SETTLEMENT,
    ApiErrorId,
    api_client,
    assert_loss_of_use_claim,
    get_claim_view,
    get_lou_view,
    make_customer_headers,
    open_claim,
    register_policyholder,
    setup_active_rental_scenario,
    setup_authorized_rental_scenario,
    setup_lou_submitted_scenario,
    setup_verified_claim_context,
    submit_lou_claim,
    validate_error,
    validate_success,
    verify_claim_coverage,
)


class TestLouEligibility:
    def test_lou_not_eligible_rejected(self, api):
        """PRD §3.7: "First, the claim's latest non-`SUPERSEDED` verification must
        be `VERIFIED` with `loss_of_use_eligible` true; otherwise submission fails
        with `ERR_LOU_NOT_ELIGIBLE` and the claim's track stays `NONE`."

        Design: Corner/validations/lou_not_eligible_rejected
        """
        ctx = setup_verified_claim_context(rental_eligible=True,
                                           loss_of_use_eligible=False)
        resp = api.create_loss_of_use_claim(
            {"claim_id": ctx["claim"]["id"], "vehicle_description": "Spare coupe",
             "period_start": "2026-08-05", "period_end": "2026-08-10",
             "claimed_amount_cents": 9000, "payout_method": "STANDARD_PER_DIEM"},
            make_customer_headers(ctx["policyholder"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LOU_NOT_ELIGIBLE)

    def test_lou_period_closed_interval_conflict(self, api):
        """PRD §3.7: "a loss-of-use period conflicts with any reservation on the
        same claim in `DRAFT`, `AUTHORIZED`, `ACTIVE`, `EXTENSION_REVIEW`, or
        `RETURNED` whenever the closed loss-of-use interval shares at least one
        calendar day with the reservation's window treated as closed on both ends
        (pickup day through return day inclusive). The check runs on whichever
        record is created later — booking a reservation over an existing
        loss-of-use period fails with `ERR_LOU_PERIOD_CONFLICT` just as submitting
        a loss-of-use claim over an existing reservation does."

        Design: Corner/validations/lou_period_closed_interval_conflict
        """
        ctx = setup_authorized_rental_scenario()  # window [08-05, 08-15)
        conflict = api.create_loss_of_use_claim(
            {"claim_id": ctx["claim"]["id"], "vehicle_description": "Spare coupe",
             "period_start": "2026-08-15", "period_end": "2026-08-18",
             "claimed_amount_cents": 9000, "payout_method": "STANDARD_PER_DIEM"},
            make_customer_headers(ctx["policyholder"]["id"]),
        )
        validate_error(conflict, ApiErrorId.ERR_LOU_PERIOD_CONFLICT)

        clear = api.create_loss_of_use_claim(
            {"claim_id": ctx["claim"]["id"], "vehicle_description": "Spare coupe",
             "period_start": "2026-08-16", "period_end": "2026-08-18",
             "claimed_amount_cents": 9000, "payout_method": "STANDARD_PER_DIEM"},
            make_customer_headers(ctx["policyholder"]["id"]),
        )
        lou = validate_success(clear, 201)
        assert_loss_of_use_claim(lou)


class TestLouDocumentationGate:
    def test_documentation_required_rejected(self, api):
        """PRD §3.7: "Approval is possible from either `SUBMITTED` or
        `DOCUMENTED`, but a `COMPARABLE_VEHICLE` payout requires
        `documentation_provided` to be true — approving one without documentation
        fails with `ERR_DOCUMENTATION_REQUIRED`."
        PRD §3.7: "Under the `STANDARD_PER_DIEM` variant, the `payout_cents` is
        simply the claim's `loss_of_use_per_diem_cents` multiplied by the billable
        days, ignoring the claimed amount entirely."

        Design: Corner/validations/documentation_required_rejected
        """
        ctx = setup_verified_claim_context()
        lou_a = submit_lou_claim(
            ctx["claim"]["id"], ctx["policyholder"]["id"],
            vehicle_description="Borrowed pickup",
            period_start="2026-08-05", period_end="2026-08-10",
            claimed_amount_cents=30000, payout_method="COMPARABLE_VEHICLE")
        lou_b = submit_lou_claim(
            ctx["claim"]["id"], ctx["policyholder"]["id"],
            vehicle_description="Spare coupe",
            period_start="2026-09-01", period_end="2026-09-05",
            claimed_amount_cents=9000, payout_method="STANDARD_PER_DIEM")

        resp = api.approve_loss_of_use_claim(lou_a["id"], ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_DOCUMENTATION_REQUIRED)

        approved = validate_success(
            api.approve_loss_of_use_claim(lou_b["id"], ADJUSTER), 200)
        assert approved["payout_cents"] == 17500, (
            f"STANDARD_PER_DIEM approves without documentation: 5 closed days "
            f"x 3500 == 17500, got {approved['payout_cents']}"
        )

    def test_customer_cannot_document_others_lou_forbidden(self, api):
        """PRD §2.9: "A `Customer` caller may act only on claims they own —
        submitting a loss-of-use claim and attaching documentation both require
        the claim's `policyholder_id` to equal the caller's `X-User-ID`."
        PRD §2.9: "Every ownership failure is rejected with
        `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/rbac/customer_cannot_document_others_lou_forbidden
        """
        holder_one = register_policyholder(full_name="Pat One",
                                           policy_number="POL-1",
                                           contact_email="p1@x.com")
        holder_two = register_policyholder(full_name="Pat Two",
                                           policy_number="POL-2",
                                           contact_email="p2@x.com")
        claim = open_claim(holder_one["id"])
        verify_claim_coverage(claim["id"], rental_eligible=True,
                              loss_of_use_eligible=True)
        lou = submit_lou_claim(claim["id"], holder_one["id"])

        resp = api.attach_lou_documentation(
            lou["id"], make_customer_headers(holder_two["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        view = get_lou_view(lou["id"])
        assert view["status"] == "SUBMITTED"
        assert view["documentation_provided"] is False


class TestLouPayoutVariants:
    def test_lou_single_day_closed_interval(self, api):
        """PRD §3.7: "Unlike the rental track's half-open windows, the loss-of-use
        period is a closed interval counting both endpoint days, so the
        `period_end` need only be on or after the `period_start` — an inverted
        period is `ERR_INVALID_PERIOD`."
        PRD §3.7: "The payout computation first derives the reasonable length of
        the period as its closed-interval day count, counting both the first and
        last day, then caps the billable length at the claim's
        `coverage_duration_cap_days`."

        Design: Corner/calculations/lou_single_day_closed_interval
        """
        ctx = setup_verified_claim_context()
        lou = submit_lou_claim(
            ctx["claim"]["id"], ctx["policyholder"]["id"],
            vehicle_description="Neighbor's hatchback",
            period_start="2026-08-05", period_end="2026-08-05",
            claimed_amount_cents=9000, payout_method="STANDARD_PER_DIEM")
        approved = validate_success(
            api.approve_loss_of_use_claim(lou["id"], ADJUSTER), 200)
        assert approved["payout_cents"] == 3500, (
            f"A single-day closed interval pays exactly one per-diem 3500, "
            f"got {approved['payout_cents']}"
        )

    def test_lou_pay_before_approve_rejected(self, api):
        """PRD §3.7: "Paying is a `SettlementApprover` action on an `APPROVED`
        loss-of-use claim (any other state is `ERR_LOU_INVALID_STATE`), and it
        requires the claim's `overall_status` to still be `OPEN`
        (`ERR_CLAIM_NOT_OPEN`)."

        Design: Corner/state_machines/lou_pay_before_approve_rejected
        """
        ctx = setup_lou_submitted_scenario()
        resp = api.pay_loss_of_use_claim(ctx["lou_claim"]["id"], SETTLEMENT)
        validate_error(resp, ApiErrorId.ERR_LOU_INVALID_STATE)


class TestLouPayoutVariantDivergence:
    def _setup_two_variants(self):
        """Two loss-of-use claims over the same 14-day closed period
        2026-08-05..2026-08-18: A STANDARD_PER_DIEM claimed 60000, B
        COMPARABLE_VEHICLE claimed 70000 with documentation attached."""
        ctx = setup_verified_claim_context()
        lou_a = submit_lou_claim(
            ctx["claim"]["id"], ctx["policyholder"]["id"],
            vehicle_description="Borrowed sedan",
            period_start="2026-08-05", period_end="2026-08-18",
            claimed_amount_cents=60000, payout_method="STANDARD_PER_DIEM")
        lou_b = submit_lou_claim(
            ctx["claim"]["id"], ctx["policyholder"]["id"],
            vehicle_description="Borrowed pickup",
            period_start="2026-08-05", period_end="2026-08-18",
            claimed_amount_cents=70000, payout_method="COMPARABLE_VEHICLE")
        attach = api_client.attach_lou_documentation(
            lou_b["id"], make_customer_headers(ctx["policyholder"]["id"]))
        validate_success(attach, 200)
        ctx.update(lou_a=lou_a, lou_b=lou_b)
        return ctx

    def test_standard_per_diem_payout(self, api):
        """PRD §3.7: "Under the `STANDARD_PER_DIEM` variant, the `payout_cents` is
        simply the claim's `loss_of_use_per_diem_cents` multiplied by the billable
        days, ignoring the claimed amount entirely."

        Design: Difficulty/dual_variant_calc/loss_of_use_variants_diverge
        """
        ctx = self._setup_two_variants()
        approved = validate_success(
            api.approve_loss_of_use_claim(ctx["lou_a"]["id"], ADJUSTER), 200)
        assert approved["payout_cents"] == 49000, (
            f"Expected 3500 x min(14, 20) == 49000, got {approved['payout_cents']}"
        )

    def test_comparable_vehicle_payout(self, api):
        """PRD §3.7: "Under the `COMPARABLE_VEHICLE` variant, the `payout_cents`
        is the lesser of the documented `claimed_amount_cents` and the
        `coverage_daily_limit_cents` multiplied by the billable days — the actual
        documented cost capped by the daily limit."

        Design: Difficulty/dual_variant_calc/loss_of_use_variants_diverge
        """
        ctx = self._setup_two_variants()
        pay_a = validate_success(
            api.approve_loss_of_use_claim(ctx["lou_a"]["id"], ADJUSTER),
            200)["payout_cents"]
        pay_b = validate_success(
            api.approve_loss_of_use_claim(ctx["lou_b"]["id"], ADJUSTER),
            200)["payout_cents"]
        assert pay_b == 70000, (
            f"Expected min(70000, 6000 x 14) == 70000, got {pay_b}"
        )
        assert pay_b - pay_a == 21000, (
            f"Variant selection must move the payout by exactly 21000 on "
            f"identical dates; got {pay_b - pay_a}"
        )


class TestClaimParallelTracks:
    def _setup_lou_denied_with_active_rental(self):
        """Active rental on the claim; a non-overlapping loss-of-use claim is
        submitted, documented, then denied."""
        ctx = setup_active_rental_scenario()
        lou = submit_lou_claim(
            ctx["claim"]["id"], ctx["policyholder"]["id"],
            vehicle_description="Spare coupe",
            period_start="2026-08-16", period_end="2026-08-18",
            claimed_amount_cents=9000, payout_method="STANDARD_PER_DIEM")
        validate_success(api_client.attach_lou_documentation(
            lou["id"], make_customer_headers(ctx["policyholder"]["id"])), 200)
        validate_success(api_client.deny_loss_of_use_claim(
            lou["id"], {"decision_reason": "insufficient proof"}, ADJUSTER), 200)
        ctx["lou_claim"] = lou
        return ctx

    def test_lou_track_progresses_independently(self, api):
        """PRD §3.2: "The two track dimensions evolve independently under the
        `overall_status` gate; the only terminal state of a claim is
        `overall_status` reaching `CLOSED`."
        PRD §3.7: "Denial is open from the same two states, accepts an optional
        `decision_reason`, lands the claim in `DENIED`, and moves the track to
        `LOU_DENIED`."

        Design: Difficulty/non_linear_state_machine/claim_parallel_tracks_independent
        """
        ctx = self._setup_lou_denied_with_active_rental()
        claim = get_claim_view(ctx["claim"]["id"])
        assert claim["loss_of_use_track_status"] == "LOU_DENIED", (
            f"The LOU dimension must progress NONE -> LOU_SUBMITTED -> "
            f"LOU_DOCUMENTED -> LOU_DENIED; got {claim['loss_of_use_track_status']}"
        )

    def test_rental_track_untouched_by_lou_denial(self, api):
        """PRD §3.2: "The two track dimensions evolve independently under the
        `overall_status` gate; the only terminal state of a claim is
        `overall_status` reaching `CLOSED`."

        Design: Difficulty/non_linear_state_machine/claim_parallel_tracks_independent
        """
        ctx = self._setup_lou_denied_with_active_rental()
        claim = get_claim_view(ctx["claim"]["id"])
        assert claim["rental_track_status"] == "RENTAL_ACTIVE", (
            f"The LOU denial must not disturb the rental dimension; "
            f"got {claim['rental_track_status']}"
        )
        assert claim["overall_status"] == "OPEN"
