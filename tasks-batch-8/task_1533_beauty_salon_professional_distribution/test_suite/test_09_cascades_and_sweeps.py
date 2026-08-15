"""Cross-entity cascades and the daily compliance sweep (PRD §2.4, §3.3,
§3.6, §3.11)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_active_salon,
    create_draft_order,
    create_sample_promotion,
    file_diversion_case,
    get_order,
    get_promotion,
    get_salon,
    make_brand,
    make_compliance_officer_headers,
    make_product,
    make_salon_buyer_headers,
    run_sweep,
    set_clock,
    setup_salon_with_credit_points,
    submit_order,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


class TestLicenseExpirySuspensionCascade:
    def _setup(self, api):
        """ACTIVE salon whose only license expires 2026-08-10; ACTIVE SAMPLE
        promotion (budget 5, 2 units per redemption); order of 1 x RETAIL
        10000 with the promotion redeemed, SUBMITTED; clock at 2026-08-15."""
        salon, consultant = create_active_salon(
            legal_name="Salon E", valid_until="2026-08-10T00:00:00Z")
        brand = make_brand()
        cream = make_product(brand["id"], base_price_cents=10000,
                             weight_grams=200)
        sachet = make_product(brand["id"], base_price_cents=500,
                              weight_grams=10)
        promo = create_sample_promotion(
            sachet["id"], code="SAMP1", budget_units=5, per_salon_cap=10,
            sample_units_per_redemption=2)
        order = create_draft_order(
            salon["id"], [{"product_id": cream["id"], "quantity": 1}])
        validate_success(api.redeem_promotion(
            order["id"], {"code": "SAMP1"},
            make_salon_buyer_headers(salon["id"])), 200)
        submit_order(order["id"], salon["id"])
        set_clock("2026-08-15T00:00:00Z")
        return salon, promo, order

    def test_sweep_expires_license_and_suspends_salon(self, api):
        """PRD §2.4: "One sweep performs three jobs: every `VERIFIED` license
        whose `valid_until` now lies before the logical clock moves to
        `EXPIRED` (and if that was the salon's last still-valid verified
        license while the salon is `ACTIVE`, the salon is suspended with
        reason `LICENSE_EXPIRED` and the full suspension cascade of §3.3
        fires)"
        PRD §2.4: "The sweep reports `expired_license_count`,
        `suspended_salon_count`, `expired_credit_points`, and
        `ended_promotion_count`."

        Design: Difficulty/transitive_cascade/license_expiry_suspension_cascade
        """
        salon, promo, order = self._setup(api)
        result = run_sweep()
        assert result["expired_license_count"] == 1
        assert result["suspended_salon_count"] == 1

        salon_after = get_salon(salon["id"])
        assert salon_after["status"] == "SUSPENDED"
        assert salon_after["suspension_reason"] == "LICENSE_EXPIRED"

    def test_suspension_cascade_cancels_order_and_reverses_redemption(self, api):
        """PRD §3.6: "System cancellation is the cascade arm: when the owning
        salon enters `SUSPENDED` or `DEACTIVATED`, orders in `SUBMITTED` are
        cancelled exactly as the buyer path from `SUBMITTED`, while orders in
        `APPROVED` are cancelled with payment moving `CAPTURED` → `REFUNDED`,
        the provisional accrual and any credit redemption reversed, and any
        applied promotion redemption reversed with reason `ACCOUNT_SUSPENDED`
        and budget restored."

        Design: Difficulty/transitive_cascade/license_expiry_suspension_cascade
        """
        salon, promo, order = self._setup(api)
        run_sweep()

        order_after = get_order(order["id"])
        assert order_after["fulfillment_status"] == "CANCELLED"
        assert order_after["payment_status"] == "VOIDED"

        promo_after = get_promotion(promo["id"])
        assert promo_after["remaining_budget_units"] == 5, (
            "the 2 redeemed units are restored to the promotion budget")

        redemptions = validate_success(api.list_promotion_redemptions(
            ADMIN, params={"limit": 100}), 200)
        ours = [r for r in redemptions if r["order_id"] == order["id"]]
        assert len(ours) == 1
        assert ours[0]["status"] == "REVERSED"
        # NOTE: no reversal_reason assertion here. PRD §3.6 pins
        # ACCOUNT_SUSPENDED only on the APPROVED cascade branch; for the
        # SUBMITTED branch it says "cancelled exactly as the buyer path from
        # SUBMITTED" (buyer path: ORDER_CANCELLED), so the specific reason
        # value on this branch is not uniquely derivable from the PRD.

        salon_after = get_salon(salon["id"])
        assert salon_after["education_credit_points"] == 0, (
            "the provisional accrual (10 points) is reversed by the cascade")


class TestDiversionSubstantiationCascade:
    def _setup(self, api):
        """ACTIVE salon with a SUBMITTED order and two MAJOR cases filed by
        the salon's consultant, both UNDER_REVIEW, awaiting adjudication by a
        different officer than the filer."""
        salon, consultant = create_active_salon(legal_name="Salon F")
        brand = make_brand()
        product = make_product(brand["id"], base_price_cents=10000)
        order = create_draft_order(
            salon["id"], [{"product_id": product["id"], "quantity": 1}])
        submit_order(order["id"], salon["id"])
        cases = []
        for note in ("marketplace listing", "retail shelf sighting"):
            case = file_diversion_case(
                salon["id"], product["id"], severity="MAJOR",
                evidence_note=note, hold_shipments=False,
                filer_consultant_id=consultant["id"])
            validate_success(api.start_diversion_review(
                case["id"], make_compliance_officer_headers("officer-1")), 200)
            cases.append(case)
        return salon, order, cases

    def test_substantiation_awards_strikes_and_recomputes_risk_score(self, api):
        """PRD §3.11: "On substantiation the case lands in `SUBSTANTIATED`,
        `adjudicated_by_user_id` is stamped, `strike_points_awarded` is set to
        the severity points, and the salon's `diversion_strike_points` grows
        by that award while its `diversion_risk_score` is recomputed"
        PRD §3.11: "the score is the sum, over the salon's `SUBSTANTIATED`
        cases only — `OPEN`, `UNDER_REVIEW`, and `DISMISSED` rows are excluded
        — of each case's severity points times a decay factor evaluated
        against the logical clock: full weight when the substantiation (dated
        by the case's `updated_at` at the substantiating transition) lies less
        than 12 months back, half weight between 12 and 24 months, and zero
        beyond 24 months"

        Design: Difficulty/transitive_cascade/diversion_substantiation_strike_cascade
        """
        salon, order, cases = self._setup(api)
        for case in cases:
            validate_success(api.substantiate_diversion_case(
                case["id"], make_compliance_officer_headers("officer-1")), 200)

        salon_after = get_salon(salon["id"])
        assert salon_after["diversion_strike_points"] == 4, (
            "two MAJOR awards of 2 points each")
        assert salon_after["diversion_risk_score"] == pytest.approx(4.0), (
            "2 cases x 2 points x decay 1.0 == 4.0")

    def test_third_strike_point_threshold_suspends_salon(self, api):
        """PRD §3.11: "When the award pushes `diversion_strike_points` to at
        least 3 and the salon is `ACTIVE`, the salon is suspended with reason
        `DIVERSION_STRIKES` and the full suspension cascade of §3.3 fires."

        Design: Difficulty/transitive_cascade/diversion_substantiation_strike_cascade
        """
        salon, order, cases = self._setup(api)
        for case in cases:
            validate_success(api.substantiate_diversion_case(
                case["id"], make_compliance_officer_headers("officer-1")), 200)

        salon_after = get_salon(salon["id"])
        assert salon_after["status"] == "SUSPENDED"
        assert salon_after["suspension_reason"] == "DIVERSION_STRIKES"

        order_after = get_order(order["id"])
        assert order_after["fulfillment_status"] == "CANCELLED"
        assert order_after["payment_status"] == "VOIDED"
        assert salon_after["education_credit_points"] == 0, (
            "the SUBMITTED order's provisional accrual is reversed")


class TestSubmitPriorityAndCreditExpiry:
    def _setup_suspended_with_stale_redemption(self, api):
        """SILVER salon with 1000 points; DRAFT order (merch 120000) carrying
        a 600-point redemption; salon then manually suspended; clock advanced
        past the accrual's 12-month expiry and swept (residual 400 points
        expire, balance 0)."""
        salon, _, _ = setup_salon_with_credit_points(1000)
        brand = make_brand()
        mask = make_product(brand["id"], base_price_cents=20000,
                            weight_grams=200)
        order = create_draft_order(
            salon["id"], [{"product_id": mask["id"], "quantity": 6}])
        validate_success(api.redeem_credits(
            order["id"], {"points": 600},
            make_salon_buyer_headers(salon["id"])), 200)
        validate_success(api.suspend_salon(
            salon["id"], {"reason": "audit"}, OFFICER), 200)
        set_clock("2027-09-02T00:00:00Z")
        run_sweep()
        return salon, order

    def test_submit_reports_account_not_active_over_credit_revalidation(self, api):
        """PRD §2.8: "Every request passes a fixed pipeline of checks,
        evaluated in this order; the first failure wins and later failures are
        masked:"
        PRD §2.8: "**Endpoint-specific business rules** — account activity,
        hazmat/method pairing, diversion holds, shipment quantities, territory
        exclusivity, quotas, uniqueness, window overlap, buffers, license
        dates, promotion eligibility, credit caps, and license availability —
        each detailed in §3 beside the workflow it guards."
        PRD §3.6: "The salon must be `ACTIVE` (`ERR_ACCOUNT_NOT_ACTIVE`)."

        Design: Difficulty/priority_pair_validation_conflict/submit_salon_suspended_beats_credit_balance
        """
        salon, order = self._setup_suspended_with_stale_redemption(api)
        resp = api.submit_order(
            order["id"], make_salon_buyer_headers(salon["id"]))
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE)
        assert get_order(order["id"])["fulfillment_status"] == "DRAFT"

    def test_sweep_expires_residual_credit_points(self, api):
        """PRD §2.4: "every accrual credit entry whose `expires_at` now lies
        before the logical clock and which still has residual points posts an
        `EXPIRY` entry of the negative residual — that is, the entry's
        `points` minus its `consumed_points` — with `consumed_points` then set
        equal to `points`."

        Design: Difficulty/priority_pair_validation_conflict/submit_salon_suspended_beats_credit_balance
        """
        salon, order = self._setup_suspended_with_stale_redemption(api)
        salon_after = get_salon(salon["id"])
        assert salon_after["education_credit_points"] == 0, (
            "the sweep expires the 400 residual points (1000 earned, 600 "
            "consumed by the redemption)")
        ledger = validate_success(api.list_credit_ledger(
            salon["id"], ADMIN, params={"limit": 100}), 200)
        expiry = [e for e in ledger if e["entry_type"] == "EXPIRY"]
        assert len(expiry) == 1
        assert expiry[0]["points"] == -400


class TestSweepIdempotenceAndDiversionAdjudication:
    def test_ops_sweep_second_run_is_noop(self, api):
        """PRD §2.4: "Time-dependent transitions fire inside an explicit
        ops-run checkpoint, invoked by a `DistributionAdmin` as the daily
        sweep."
        PRD §2.4: "One sweep performs three jobs: every `VERIFIED` license
        whose `valid_until` now lies before the logical clock moves to
        `EXPIRED` (and if that was the salon's last still-valid verified
        license while the salon is `ACTIVE`, the salon is suspended with
        reason `LICENSE_EXPIRED` and the full suspension cascade of §3.3
        fires); every promotion in `ACTIVE` or `PAUSED` whose `ends_at` now
        lies before the logical clock moves to `ENDED`; and every accrual
        credit entry whose `expires_at` now lies before the logical clock and
        which still has residual points posts an `EXPIRY` entry of the
        negative residual"

        Design: Corner/cross_cutting_complexity_layers/ops_sweep_second_run_is_noop
        """
        salon, _ = create_active_salon(
            legal_name="Salon 49", valid_until="2026-08-10T00:00:00Z")
        brand = make_brand()
        sachet = make_product(brand["id"], base_price_cents=500,
                              weight_grams=10)
        create_sample_promotion(
            sachet["id"], code="SWP49", budget_units=5, per_salon_cap=5,
            ends_at="2026-08-10T00:00:00Z")
        set_clock("2026-08-15T00:00:00Z")

        first = run_sweep()
        assert first["expired_license_count"] == 1
        assert first["suspended_salon_count"] == 1
        assert first["ended_promotion_count"] == 1

        second = run_sweep()
        assert second["expired_license_count"] == 0
        assert second["suspended_salon_count"] == 0
        assert second["ended_promotion_count"] == 0
        assert second["expired_credit_points"] == 0

    def test_diversion_case_terminal_lockdown(self, api):
        """PRD §3.11: "Both `SUBSTANTIATED` and `DISMISSED` are terminal —
        transitions attempted from them are rejected with
        `ERR_INVALID_DIVERSION_CASE_STATE`."

        Design: Corner/state_machines/diversion_case_terminal_lockdown
        """
        salon, consultant = create_active_salon(legal_name="Salon 2")
        brand = make_brand()
        product = make_product(brand["id"], base_price_cents=3000)
        case = file_diversion_case(
            salon["id"], product["id"], severity="MINOR",
            evidence_note="flea market booth", hold_shipments=False,
            filer_consultant_id=consultant["id"])
        validate_success(api.start_diversion_review(
            case["id"], make_compliance_officer_headers("officer-a")), 200)
        validate_success(api.substantiate_diversion_case(
            case["id"], make_compliance_officer_headers("officer-a")), 200)
        assert get_salon(salon["id"])["diversion_strike_points"] == 1

        resp = api.substantiate_diversion_case(
            case["id"], make_compliance_officer_headers("officer-b"))
        validate_error(resp, ApiErrorId.ERR_INVALID_DIVERSION_CASE_STATE)
        assert get_salon(salon["id"])["diversion_strike_points"] == 1, (
            "no extra strike points are awarded from a terminal state")

    def test_diversion_filer_cannot_substantiate_own_case(self, api):
        """PRD §3.11: "Substantiation requires `UNDER_REVIEW` and a
        segregation-of-duties check: the caller's `X-User-ID` must differ from
        the case's `filed_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`)."

        Design: Corner/rbac/diversion_filer_cannot_substantiate_own_case
        """
        salon, _ = create_active_salon(legal_name="Salon 45")
        brand = make_brand()
        product = make_product(brand["id"], base_price_cents=3000)
        case = file_diversion_case(
            salon["id"], product["id"], severity="MINOR",
            evidence_note="seen at retail", hold_shipments=False,
            filer_officer_id="officer-7")
        validate_success(api.start_diversion_review(
            case["id"], make_compliance_officer_headers("officer-7")), 200)

        resp = api.substantiate_diversion_case(
            case["id"], make_compliance_officer_headers("officer-7"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        substantiated = validate_success(api.substantiate_diversion_case(
            case["id"], make_compliance_officer_headers("officer-8")), 200)
        assert substantiated["status"] == "SUBSTANTIATED"
        assert substantiated["strike_points_awarded"] == 1
        assert get_salon(salon["id"])["diversion_strike_points"] == 1
