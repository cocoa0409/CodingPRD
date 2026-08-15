"""Reconciliations, aging boundaries, write-off gates, derived unreconciled count."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_reconciliation_payload, create_reconciling_item_payload,
    set_clock, setup_open_period_with_entity,
    drive_entity_period_to_subledger_cut,
    CONTROLLER, PREPARER, APPROVER,
    make_preparer_headers,
)
from test_helpers import api_client


def _setup_ep_with_subledger_cut(api):
    """Period+entity opened; one AR cutoff confirmed → ep in SUBLEDGER_CUT."""
    period, entity, ep = setup_open_period_with_entity()
    drive_entity_period_to_subledger_cut(ep["id"])
    return period, entity, ep


class TestReconToleranceBoundary:
    def test_recon_tolerance_at_500_is_within_tolerance(self, api):
        """PRD §3.6: "The system computes `difference_minor` as the GL balance
        minus the subledger balance with sign preserved, and
        `is_within_tolerance`, which is true when the absolute difference is no
        more than five hundred minor units."

        Design: Corner/calculations/recon_tolerance_boundary_is_within_tolerance
        """
        period, entity, ep = setup_open_period_with_entity()
        rec = validate_success(api.create_reconciliation(
            ep["id"],
            create_reconciliation_payload(account_code="1010", gl_balance_minor=100500,
                                           subledger_balance_minor=100000),
            PREPARER), 201)
        assert rec["difference_minor"] == 500
        assert rec["is_within_tolerance"] is True

    def test_recon_tolerance_at_501_is_out_of_tolerance(self, api):
        """PRD §3.6: "`is_within_tolerance`, which is true when the absolute
        difference is no more than five hundred minor units."

        Design: Corner/calculations/recon_tolerance_boundary_is_within_tolerance
        """
        period, entity, ep = setup_open_period_with_entity()
        rec = validate_success(api.create_reconciliation(
            ep["id"],
            create_reconciliation_payload(account_code="1020", gl_balance_minor=100501,
                                           subledger_balance_minor=100000),
            PREPARER), 201)
        assert rec["difference_minor"] == 501
        assert rec["is_within_tolerance"] is False


class TestAgingBucketBoundary:
    def test_aging_bucket_30_vs_31_day_boundary(self, api):
        """PRD §3.6: "An item whose `item_date` is on or before `period_end` and
        which is not yet past due lands in `CURRENT`; one through thirty days past
        lands in `AGE_1_30`; thirty-one through sixty in `AGE_31_60`; sixty-one
        through ninety in `AGE_61_90`; and ninety-one days past or more lands in
        `AGE_OVER_90`. The boundaries are exact: exactly thirty days past is
        `AGE_1_30`, exactly thirty-one is `AGE_31_60`, exactly ninety is
        `AGE_61_90`, and exactly ninety-one is `AGE_OVER_90`."

        Design: Difficulty/boundary_precision_check/recon_aging_bucket_30_vs_31_day_boundary
        """
        period, entity, ep = _setup_ep_with_subledger_cut(api)
        rec = validate_success(api.create_reconciliation(
            ep["id"],
            create_reconciliation_payload(account_code="1010-BANK"),
            PREPARER), 201)
        item = validate_success(api.create_reconciling_item(
            rec["id"],
            create_reconciling_item_payload(item_date="2026-01-31T00:00:00Z"),
            PREPARER), 201)

        # advance to exactly period_end + 30 days
        set_clock("2026-03-02T00:00:00Z")
        items = validate_success(api.list_reconciling_items(rec["id"], PREPARER), 200)
        assert items[0]["aging_bucket"] == "AGE_1_30"

        # advance to period_end + 31 days
        set_clock("2026-03-03T00:00:00Z")
        items = validate_success(api.list_reconciling_items(rec["id"], PREPARER), 200)
        assert items[0]["aging_bucket"] == "AGE_31_60"

    def test_aging_bucket_at_period_end_is_current(self, api):
        """PRD §3.6: "An item whose `item_date` is on or before `period_end` and
        which is not yet past due lands in `CURRENT`".

        Design: Difficulty/boundary_precision_check/recon_aging_bucket_30_vs_31_day_boundary
        """
        period, entity, ep = _setup_ep_with_subledger_cut(api)
        rec = validate_success(api.create_reconciliation(
            ep["id"], create_reconciliation_payload(account_code="1010-BANK"), PREPARER), 201)
        # clock still in-period (2026-01-15); item dated at period_end
        item = validate_success(api.create_reconciling_item(
            rec["id"],
            create_reconciling_item_payload(item_date="2026-01-31T00:00:00Z"),
            PREPARER), 201)
        assert item["aging_bucket"] == "CURRENT"


class TestWriteOffGates:
    def test_writeoff_exactly_at_materiality_rejected(self, api):
        """PRD §3.6: "the item's absolute `amount_minor` must be strictly below the
        period's `materiality_threshold_minor` — items at or above materiality
        cannot be written off and are rejected with
        `ERR_WRITEOFF_ABOVE_MATERIALITY`".

        Design: Difficulty/boundary_precision_check/writeoff_exactly_at_materiality_rejected_zero_item_count
        """
        period, entity, ep = _setup_ep_with_subledger_cut(api)
        rec = validate_success(api.create_reconciliation(
            ep["id"], create_reconciliation_payload(account_code="1010-BANK"), PREPARER), 201)
        get_success_data(api.review_reconciliation(rec["id"], make_preparer_headers("prep-1")))
        # item dated 2026-01-20; clock advanced to 2026-03-12 → 40 days past period_end → AGE_31_60
        item_at = validate_success(api.create_reconciling_item(
            rec["id"],
            create_reconciling_item_payload(description="At materiality",
                                              amount_minor=10000,
                                              item_date="2026-01-20T00:00:00Z"),
            PREPARER), 201)
        set_clock("2026-03-12T00:00:00Z")
        res = api.write_off_reconciling_item(item_at["id"], APPROVER)
        validate_error(res, ApiErrorId.ERR_WRITEOFF_ABOVE_MATERIALITY, expected_status=409)

    def test_writeoff_one_below_materiality_succeeds(self, api):
        """PRD §3.6: "the item's absolute `amount_minor` must be strictly below
        the period's `materiality_threshold_minor` — items at or above materiality
        cannot be written off and are rejected with
        `ERR_WRITEOFF_ABOVE_MATERIALITY` — and the item's `aging_bucket` must be
        `AGE_31_60`, `AGE_61_90`, or `AGE_OVER_90`".

        Design: Difficulty/boundary_precision_check/writeoff_exactly_at_materiality_rejected_zero_item_count
        """
        period, entity, ep = _setup_ep_with_subledger_cut(api)
        rec = validate_success(api.create_reconciliation(
            ep["id"], create_reconciliation_payload(account_code="1010-BANK"), PREPARER), 201)
        get_success_data(api.review_reconciliation(rec["id"], make_preparer_headers("prep-1")))
        item_below = validate_success(api.create_reconciling_item(
            rec["id"],
            create_reconciling_item_payload(description="Below materiality",
                                              amount_minor=9999,
                                              item_date="2026-01-20T00:00:00Z"),
            PREPARER), 201)
        set_clock("2026-03-12T00:00:00Z")
        written = validate_success(api.write_off_reconciling_item(item_below["id"], APPROVER), 200)
        assert written["status"] == "WRITTEN_OFF"

    def test_writeoff_too_young_rejected(self, api):
        """PRD §3.6: "the item's `aging_bucket` must be `AGE_31_60`, `AGE_61_90`,
        or `AGE_OVER_90`, because `CURRENT` and `AGE_1_30` items are too young to
        write off (`ERR_WRITEOFF_TOO_YOUNG`)."

        Design: Corner/errors/writeoff_too_young_rejected
        """
        period, entity, ep = _setup_ep_with_subledger_cut(api)
        rec = validate_success(api.create_reconciliation(
            ep["id"], create_reconciliation_payload(account_code="1010"), PREPARER), 201)
        get_success_data(api.review_reconciliation(rec["id"], make_preparer_headers("prep-1")))
        item = validate_success(api.create_reconciling_item(
            rec["id"],
            create_reconciling_item_payload(description="young item",
                                              amount_minor=100,
                                              item_date="2026-01-31T00:00:00Z"),
            PREPARER), 201)
        # clock 10 days past period_end → AGE_1_30
        set_clock("2026-02-10T00:00:00Z")
        res = api.write_off_reconciling_item(item["id"], APPROVER)
        validate_error(res, ApiErrorId.ERR_WRITEOFF_TOO_YOUNG, expected_status=409)


class TestUnreconciledCountDerived:
    def test_unreconciled_count_bumps_on_create(self, api):
        """PRD §3.6: "Creation also bumps the entity-period's
        `unreconciled_count`, which counts reconciliation rows not yet in
        `CLEARED`".

        Design: Corner/cross_cutting_layers/derived_field_unreconciled_count_reconciles_on_clear
        """
        period, entity, ep = _setup_ep_with_subledger_cut(api)
        rec = validate_success(api.create_reconciliation(
            ep["id"],
            create_reconciliation_payload(account_code="1010", gl_balance_minor=105000,
                                           subledger_balance_minor=100000),
            PREPARER), 201)
        after = validate_success(api.get_entity_period(ep["id"], PREPARER), 200)
        assert after["unreconciled_count"] == 1

    def test_unreconciled_count_drops_on_clear(self, api):
        """PRD §3.6: "A successful clear records `cleared_by_user_id`, moves the
        reconciliation to `CLEARED`, recomputes `unreconciled_count`, and appends
        a `RECON_CLEARED` event."

        Design: Corner/cross_cutting_layers/derived_field_unreconciled_count_reconciles_on_clear
        """
        period, entity, ep = _setup_ep_with_subledger_cut(api)
        rec = validate_success(api.create_reconciliation(
            ep["id"],
            create_reconciliation_payload(account_code="1010", gl_balance_minor=105000,
                                           subledger_balance_minor=100000),
            PREPARER), 201)
        # review by prep-1, clear by prep-2 (SoD)
        get_success_data(api.review_reconciliation(rec["id"], make_preparer_headers("prep-1")))
        # Difference is 5000 → outside tolerance. Per PRD §3.6 the open
        # reconciling items explain the difference: adding a +5000 item brings
        # the recomputed difference to 0 (within tolerance), so the clear gate
        # ("a clear attempted with open items and an out-of-tolerance difference
        # is rejected") passes with the item still OPEN. Resolving it first
        # would remove it from the open set and push the difference back to
        # 5000, making the clear illegal.
        item = validate_success(api.create_reconciling_item(
            rec["id"],
            create_reconciling_item_payload(description="reconciling", amount_minor=5000,
                                              item_date="2026-01-20T00:00:00Z"),
            PREPARER), 201)
        get_success_data(api.clear_reconciliation(rec["id"], make_preparer_headers("prep-2")))
        after = validate_success(api.get_entity_period(ep["id"], PREPARER), 200)
        assert after["unreconciled_count"] == 0
