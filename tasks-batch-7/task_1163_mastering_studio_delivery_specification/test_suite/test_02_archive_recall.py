"""Archive recall pricing: tiered per-GB fee vs minimum floor (PRD §3.8, §2.7)."""
from test_helpers import (
    validate_success, validate_error, get_success_data, is_iso8601_timestamp,
    setup_recalled_project, setup_archived_project, create_credit_adjustment_payload,
    make_client_headers, TEST_USERS, GB_BYTES, ApiErrorId,
)

MANAGER = TEST_USERS["manager_headers"]


class TestRecallFeeTieredVsMinFloor:

    def test_recall_fee_hot_one_gb_floored_at_minimum(self, api):
        """PRD §3.8: "The fee is tiered by storage class over the archive's size in
        whole gigabytes: the byte count is divided by 1,073,741,824 and rounded up —
        an archive even one byte over a gigabyte boundary bills the next whole
        gigabyte, and anything under a gigabyte still bills one — then multiplied by
        the class rate: 500 cents per gigabyte for `HOT`, 1,000 for `WARM`, 2,000 for
        `COLD`, and 4,000 for `GLACIER`. A floor protects the studio from trivial
        recalls: if the computed fee is under 1,000 cents, the charge is 1,000 cents —
        ten dollars — regardless."

        1 GB * 500 = 500 cents is under the floor, so the charge is 1000 cents.

        Design: Difficulty/dual_variant_calc/archive_recall_fee_tiered_vs_min_floor
        """
        ctx = setup_recalled_project(
            storage_class="HOT", archive_size_bytes=GB_BYTES, credit_cents=500000)
        bundle = ctx["bundle"]
        assert bundle["recall_fee_cents"] == 1000, (
            f"min floor must dominate: expected 1000, got {bundle['recall_fee_cents']}")

    def test_recall_moves_bundle_to_pending_and_debits_fee(self, api):
        """PRD §3.8: "The recall moves the bundle `NONE → PENDING`, stamps
        `recalled_at`, computes the recall fee into `recall_fee_cents`, debits the
        client's `account_credit_cents` by that fee with the usual
        `ERR_INSUFFICIENT_CREDIT` (HTTP 402) guard, moves the project
        `ARCHIVED → RECALLED`, and increments the project's `version`."

        Client seeded with 500000 pays 80000 at approval and 1000 at recall.

        Design: Difficulty/dual_variant_calc/archive_recall_fee_tiered_vs_min_floor
        """
        ctx = setup_recalled_project(
            storage_class="HOT", archive_size_bytes=GB_BYTES, credit_cents=500000)
        bundle = ctx["bundle"]
        assert bundle["recall_status"] == "PENDING"
        assert is_iso8601_timestamp(bundle.get("recalled_at", "")), (
            "recalled_at must be stamped on recall")
        assert ctx["project"]["status"] == "RECALLED"
        client = validate_success(api.get_client(ctx["client"]["id"], MANAGER), 200)
        assert client["account_credit_cents"] == 500000 - 80000 - 1000


class TestRecallFeeNestedRoundingOrder:

    def test_recall_fee_ceils_bytes_to_gb_before_multiplying(self, api):
        """PRD §3.8: "The fee is tiered by storage class over the archive's size in
        whole gigabytes: the byte count is divided by 1,073,741,824 and rounded up —
        an archive even one byte over a gigabyte boundary bills the next whole
        gigabyte, and anything under a gigabyte still bills one — then multiplied by
        the class rate: 500 cents per gigabyte for `HOT`, 1,000 for `WARM`, 2,000 for
        `COLD`, and 4,000 for `GLACIER`."

        1610612736 bytes = 1.5 GB -> ceil to 2 GB -> 2 * 2000 (COLD) = 4000 cents.
        A multiply-first order would yield 3000 instead.

        Design: Difficulty/combinatorial_formula/recall_fee_mode_b_nested_rounding_order
        """
        ctx = setup_recalled_project(
            storage_class="COLD", archive_size_bytes=1610612736, credit_cents=500000)
        assert ctx["bundle"]["recall_fee_cents"] == 4000, (
            f"ceil(1.5 GB)=2 GB at 2000/GB must give 4000, got "
            f"{ctx['bundle']['recall_fee_cents']}")

    def test_recall_fee_tier_dominates_when_above_floor(self, api):
        """PRD §3.8: "A floor protects the studio from trivial recalls: if the
        computed fee is under 1,000 cents, the charge is 1,000 cents — ten dollars —
        regardless." PRD §3.8: "then multiplied by the class rate: 500 cents per
        gigabyte for `HOT`, 1,000 for `WARM`, 2,000 for `COLD`, and 4,000 for
        `GLACIER`."

        1 GB at GLACIER = 4000 cents; the floor does not apply.

        Design: Difficulty/combinatorial_formula/recall_fee_mode_b_nested_rounding_order
        """
        ctx = setup_recalled_project(
            storage_class="GLACIER", archive_size_bytes=GB_BYTES, credit_cents=500000)
        assert ctx["bundle"]["recall_fee_cents"] == 4000


class TestRecallInsufficientCredit:

    def test_recall_with_credit_below_fee_rejected(self, api):
        """PRD §2.7: "No debit may drive the balance below zero: if the balance after
        the debit would be negative, the operation is rejected with
        `ERR_INSUFFICIENT_CREDIT` (HTTP 402)." PRD §3.8: "debits the client's
        `account_credit_cents` by that fee with the usual `ERR_INSUFFICIENT_CREDIT`
        (HTTP 402) guard".

        GLACIER 10 GB bundle -> fee 40000 cents; balance drained to 100 cents.

        Design: Corner/errors/err_insufficient_credit_on_recall
        """
        ctx = setup_archived_project(
            storage_class="GLACIER", archive_size_bytes=10 * GB_BYTES,
            credit_cents=200000)
        client_id = ctx["client"]["id"]
        # Balance is 200000 - 80000 (approval) = 120000; drain to 100.
        get_success_data(api.create_credit_adjustment(
            client_id,
            create_credit_adjustment_payload(amount_cents=-119900, reason="drain"),
            MANAGER))
        res = api.recall_project(ctx["project"]["id"], make_client_headers(client_id))
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_CREDIT, expected_status=402)
