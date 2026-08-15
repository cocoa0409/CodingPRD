"""The spend ledger: accrual entries, posting, correction, and reserve math."""
from test_helpers import (
    assert_accrual_entry,
    create_posted_accrual,
    create_submitted_accrual,
    get_success_data,
    setup_active_matter,
    validate_error,
    validate_success,
)
from test_helpers import ApiErrorId, AccrualEntryStatus, Posture


class TestLedgerShape:
    def test_accrual_entry_common_fields_false_immutability(self, api):
        """PRD §2.4: "One entity breaks this pattern deliberately: the AccrualEntry is
        an append-only ledger row and carries only `id` and `created_at`. It has no
        `updated_at` and no `version`; ledger rows are never edited in place, only
        reversed by compensating entries (see §3.4)."

        Design: Corner/entities/accrual_entry_common_fields_false_immutability
        """
        ctx = setup_active_matter()
        entry = validate_success(api.create_accrual_entry(
            ctx["matter_id"],
            {"engagement_id": ctx["engagement_id"], "period": "2026-08",
             "entry_kind": "ACCRUAL", "amount_cents": 100_000},
            ctx["counsel"]), 201)
        assert entry["status"] == AccrualEntryStatus.DRAFT.value
        assert_accrual_entry(entry)
        assert entry["created_at"], "created_at must be populated"


class TestReserveComputation:
    def test_reserve_recognition_floor_at_zero(self, api):
        """PRD §3.1: "Third, the matter's `accrued_to_date_cents` is subtracted, and
        fourth, the result is floored at zero."

        Design: Corner/calculations/reserve_recognition_floor_at_zero
        """
        # TIER_1: expected loss = (100,000 + 100,000) * 10 // 200 = 10,000 < 25,000,000
        # scaled base = 500,000 * 10 // 100 = 50,000; posting 75,000 drives it negative.
        ctx = setup_active_matter(exposure=(100_000, 100_000, 10))
        create_posted_accrual(ctx, period="2026-08", amount_cents=75_000)
        matter = get_success_data(api.get_matter(ctx["matter_id"], ctx["counsel"]))
        assert matter["exposure_tier"] == "TIER_1"
        assert matter["accrued_to_date_cents"] == 75_000
        assert matter["reserve_amount_cents"] == 0, \
            "reserve must floor at zero when accrued exceeds the scaled base"

    def test_reserve_evaluation_order_subtracts_accrued(self, api):
        """PRD §3.1: "First a base is read from the tier table: 500,000 cents for
        `TIER_1`, 2,500,000 for `TIER_2`, 10,000,000 for `TIER_3`, and 50,000,000 for
        `TIER_4`. Second, the base is scaled by probability: multiplied by
        `probability_of_loss_pct` and divided by one hundred with floor division.
        Third, the matter's `accrued_to_date_cents` is subtracted, and fourth, the
        result is floored at zero."
        PRD §3.1: "The reserve recomputes whenever the tier recomputes, whenever an
        accrual entry posts or is voided, and at resolution and reopen."

        Design: Difficulty/combinatorial_formula/reserve_recognition_evaluation_order_circular
        """
        # TIER_2: expected loss = (40,000,000 + 50,000,000) * 60 // 200 = 27,000,000
        ctx = setup_active_matter(exposure=(40_000_000, 50_000_000, 60))
        create_posted_accrual(ctx, period="2026-08", amount_cents=400_000)
        matter = get_success_data(api.get_matter(ctx["matter_id"], ctx["counsel"]))
        assert matter["exposure_tier"] == "TIER_2"
        assert matter["accrued_to_date_cents"] == 400_000
        # max(0, 2,500,000 * 60 // 100 - 400,000) = 1,100,000
        assert matter["reserve_amount_cents"] == 1_100_000, (
            f"tier base -> probability scale -> subtract accrued -> floor: "
            f"expected 1,100,000, got {matter['reserve_amount_cents']}")

    def test_reserve_reopen_restores_full_scaled_value(self, api):
        """PRD §3.9: "Reopening clears `resolved_at` to null while retaining
        `resolution_type` for audit, restores the reserve to its full
        probability-scaled value under the reopened variant — the accrued subtraction
        is skipped, historical spend being treated as sunk — and lands the matter in
        `REOPENED`, which carries `ASSESSMENT`-equivalent privileges"

        Design: Difficulty/combinatorial_formula/reserve_recognition_evaluation_order_circular
        """
        ctx = setup_active_matter(exposure=(40_000_000, 50_000_000, 60))
        create_posted_accrual(ctx, period="2026-08", amount_cents=400_000)
        get_success_data(api.resolve_matter(ctx["matter_id"], "DISMISSAL", ctx["counsel"]))
        get_success_data(api.reopen_matter(ctx["matter_id"],
                                           "Appeal filed by adverse party", ctx["dgc"]))
        matter = get_success_data(api.get_matter(ctx["matter_id"], ctx["counsel"]))
        assert matter["status"] == "REOPENED"
        # reopened variant: reserve = 2,500,000 * 60 // 100 = 1,500,000 (no subtraction)
        assert matter["reserve_amount_cents"] == 1_500_000


class TestAdjustmentReversal:
    def test_accrual_adjustment_reversal_voids_original(self, api):
        """PRD §3.4: "Posting an `ADJUSTMENT` additionally voids the entry it reverses:
        the reversed entry moves `POSTED` → `VOID` under system control and its
        original amount comes back out of `accrued_to_date_cents`, the compensating
        invariant that keeps the ledger balanced."

        Design: Corner/state_machines/accrual_adjustment_reversal_voids_original
        """
        ctx = setup_active_matter()
        original = create_posted_accrual(ctx, period="2026-07", amount_cents=500_000)
        adjustment = create_submitted_accrual(
            ctx, period="2026-08", entry_kind="ADJUSTMENT", amount_cents=-500_000,
            reverses_entry_id=original["id"])

        posted_adjustment = validate_success(
            api.post_accrual_entry(adjustment["id"], ctx["fin"]))
        assert posted_adjustment["status"] == AccrualEntryStatus.POSTED.value
        reversed_entry = get_success_data(
            api.get_accrual_entry(original["id"], ctx["fin"]))
        assert reversed_entry["status"] == AccrualEntryStatus.VOID.value, \
            "posting the ADJUSTMENT must void the entry it reverses"


class TestPeriodBucketUniqueness:
    def test_second_posted_accrual_same_bucket_rejected(self, api):
        """PRD §3.4: "For an `ACCRUAL` or `INVOICE`, posting is refused with
        `ERR_DUPLICATE` when another `POSTED` entry already exists for the same
        engagement, period, and entry kind: one posted entry per `engagement_id`,
        `period`, and `entry_kind` triple."

        Design: Difficulty/resource_temporal_overlap/accrual_period_bucket_uniqueness
        """
        ctx = setup_active_matter(second_engagement=True)
        create_posted_accrual(ctx, engagement_id=ctx["engagement_id"],
                              period="2026-08", amount_cents=100_000)
        duplicate = create_submitted_accrual(ctx, engagement_id=ctx["engagement_id"],
                                             period="2026-08", amount_cents=50_000)
        resp = api.post_accrual_entry(duplicate["id"], ctx["fin"])
        validate_error(resp, ApiErrorId.ERR_DUPLICATE)

    def test_same_period_bucket_on_other_engagement_permitted(self, api):
        """PRD §3.4: "For an `ACCRUAL` or `INVOICE`, posting is refused with
        `ERR_DUPLICATE` when another `POSTED` entry already exists for the same
        engagement, period, and entry kind: one posted entry per `engagement_id`,
        `period`, and `entry_kind` triple."
        PRD §3.4: "Formally, a matter's `accrued_to_date_cents` is the sum of
        `amount_cents` over its `POSTED` accrual entries — `DRAFT`, `SUBMITTED`, and
        `VOID` rows never count — plus the `amount_cents` of its `DISBURSED` payment
        requests whose disbursement rail reads `SENT` or `CONFIRMED`."

        Design: Difficulty/resource_temporal_overlap/accrual_period_bucket_uniqueness
        """
        ctx = setup_active_matter(second_engagement=True)
        create_posted_accrual(ctx, engagement_id=ctx["engagement_id"],
                              period="2026-08", amount_cents=100_000)
        other = create_submitted_accrual(ctx, engagement_id=ctx["engagement2_id"],
                                         period="2026-08", amount_cents=50_000)
        posted = validate_success(api.post_accrual_entry(other["id"], ctx["fin"]))
        assert posted["status"] == AccrualEntryStatus.POSTED.value
        matter = get_success_data(api.get_matter(ctx["matter_id"], ctx["counsel"]))
        assert matter["accrued_to_date_cents"] == 150_000


class TestPostingCascadeAndUtilizationBoundaries:
    def test_accrual_post_updates_rollup_and_utilization(self, api):
        """PRD §3.4: "The posted amount is added to the matter's
        `accrued_to_date_cents`; if the matter has an `APPROVED` budget its
        `utilization_pct` is recomputed"
        PRD §3.2: "Utilization is the matter's accrued spend as a percentage of the
        fiscal-year budget: `accrued_to_date_cents` multiplied by 100, divided by
        `fy_budget_cents`, floored to a whole percent"

        Design: Difficulty/transitive_cascade/accrual_post_cascade_rollup_utilization_posture
        """
        ctx = setup_active_matter(fy_budget_cents=1_000_000)
        create_posted_accrual(ctx, period="2026-07", amount_cents=500_000)
        create_posted_accrual(ctx, period="2026-08", amount_cents=400_000)

        matter = get_success_data(api.get_matter(ctx["matter_id"], ctx["counsel"]))
        assert matter["accrued_to_date_cents"] == 900_000
        budget = get_success_data(api.get_budget(ctx["budget_id"], ctx["fin"]))
        # floor(900,000 * 100 / 1,000,000) = 90
        assert budget["utilization_pct"] == 90

    def test_accrual_post_crossing_90_flips_posture_restricted(self, api):
        """PRD §3.4: "and if that recomputation pushes utilization to 90 or above, the
        posture ladder re-evaluates and the matter may flip `OPEN` → `RESTRICTED` on
        this posting — the threshold trigger that tightens the matter mid-flight."
        PRD §2.9: "Otherwise, if an `APPROVED` budget exists and its `utilization_pct`
        is at least 90, the posture is `RESTRICTED` — utilization of exactly 90
        triggers this rung."

        Design: Difficulty/transitive_cascade/accrual_post_cascade_rollup_utilization_posture
        """
        ctx = setup_active_matter(fy_budget_cents=1_000_000)
        create_posted_accrual(ctx, period="2026-07", amount_cents=500_000)
        before = get_success_data(api.get_matter(ctx["matter_id"], ctx["counsel"]))
        assert before["posture"] == Posture.OPEN.value

        create_posted_accrual(ctx, period="2026-08", amount_cents=400_000)
        after = get_success_data(api.get_matter(ctx["matter_id"], ctx["counsel"]))
        assert after["posture"] == Posture.RESTRICTED.value, \
            "utilization crossing to exactly 90 must flip posture OPEN -> RESTRICTED"

    def test_utilization_899999_reads_89_and_stays_open(self, api):
        """PRD §3.2: "Utilization is the matter's accrued spend as a percentage of the
        fiscal-year budget: `accrued_to_date_cents` multiplied by 100, divided by
        `fy_budget_cents`, floored to a whole percent — so 89,999 cents accrued against
        a 100,000-cent budget reads 89, not 90."
        PRD §2.9: "Otherwise, if an `APPROVED` budget exists and its `utilization_pct`
        is at least 90, the posture is `RESTRICTED` — utilization of exactly 90
        triggers this rung."

        Design: Difficulty/boundary_precision_check/budget_utilization_floor_boundary_899999_stays_open
        """
        ctx = setup_active_matter(fy_budget_cents=1_000_000)
        create_posted_accrual(ctx, period="2026-08", amount_cents=899_999)
        budget = get_success_data(api.get_budget(ctx["budget_id"], ctx["fin"]))
        # floor(899,999 * 100 / 1,000,000) = 89
        assert budget["utilization_pct"] == 89
        matter = get_success_data(api.get_matter(ctx["matter_id"], ctx["counsel"]))
        assert matter["posture"] == Posture.OPEN.value, \
            "89 < 90: the >= boundary must not be crossed"

    def test_utilization_900000_reads_90_and_restricts(self, api):
        """PRD §3.2: "Utilization is the matter's accrued spend as a percentage of the
        fiscal-year budget: `accrued_to_date_cents` multiplied by 100, divided by
        `fy_budget_cents`, floored to a whole percent — so 89,999 cents accrued against
        a 100,000-cent budget reads 89, not 90."
        PRD §2.9: "Otherwise, if an `APPROVED` budget exists and its `utilization_pct`
        is at least 90, the posture is `RESTRICTED` — utilization of exactly 90
        triggers this rung."

        Design: Difficulty/boundary_precision_check/budget_utilization_floor_boundary_899999_stays_open
        """
        ctx = setup_active_matter(fy_budget_cents=1_000_000)
        create_posted_accrual(ctx, period="2026-08", amount_cents=900_000)
        budget = get_success_data(api.get_budget(ctx["budget_id"], ctx["fin"]))
        assert budget["utilization_pct"] == 90
        matter = get_success_data(api.get_matter(ctx["matter_id"], ctx["counsel"]))
        assert matter["posture"] == Posture.RESTRICTED.value
