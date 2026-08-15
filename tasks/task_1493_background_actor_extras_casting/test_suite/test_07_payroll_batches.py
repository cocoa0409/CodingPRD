"""Payroll batch assembly, submission, acknowledgment, SoD, and OCC."""
from test_helpers import (
    ABSENT_UUID,
    TEST_USERS,
    ApiErrorId,
    add_batch_item,
    assert_payroll_batch,
    create_batch,
    create_production,
    make_actor_headers,
    make_payroll_headers,
    setup_issued_voucher,
    setup_open_batch_with_voucher,
    setup_submitted_batch,
    setup_wrapped_day,
    submit_batch,
    validate_error,
    validate_success,
)

PAYROLL = TEST_USERS["payroll_headers"]

# Canonical day: NONUNION rate 10000, timely meal 12:00-12:30, wrap 16:00
# -> net 510 -> issued gross 10938.
DAY = {
    "meals": [("2026-08-10T12:00:00Z", "2026-08-10T12:30:00Z")],
    "wrap_at": "2026-08-10T16:00:00Z",
}


class TestBatchAssembly:
    def test_batch_submit_empty_returns_422(self, api, payroll_headers):
        """PRD §3.8: "the batch must hold at least one voucher — an empty
        submission fails with `ERR_BATCH_EMPTY` (HTTP 422)."

        Design: Corner/validations/batch_submit_empty_returns_422
        """
        prod = create_production(active=True)
        batch = create_batch(prod["id"], creator="pc-1")
        assert batch["status"] == "OPEN"
        assert batch["voucher_count"] == 0
        res = api.submit_batch(batch["id"], payroll_headers)
        validate_error(res, ApiErrorId.ERR_BATCH_EMPTY)
        batch_after = validate_success(
            api.get_payroll_batch(batch["id"], payroll_headers), 200
        )
        assert batch_after["status"] == "OPEN"

    def test_add_draft_voucher_not_submittable(self, api, payroll_headers):
        """PRD §3.8: "The voucher itself must be `ISSUED`, must carry a null
        `payroll_batch_id`, and must belong to the same production as the batch;
        any violation fails with `ERR_VOUCHER_NOT_SUBMITTABLE`."

        Design: Corner/validations/add_draft_voucher_not_submittable
        """
        prod, call, actor, booking, voucher = setup_wrapped_day(
            wrap_at="2026-08-10T12:00:00Z"
        )
        assert voucher["status"] == "DRAFT"  # never issued
        batch = create_batch(prod["id"], creator="pc-1")
        res = api.add_batch_item(
            batch["id"],
            {"voucher_id": voucher["id"], "expected_batch_version": batch["version"]},
            payroll_headers,
        )
        validate_error(res, ApiErrorId.ERR_VOUCHER_NOT_SUBMITTABLE)

    def test_items_on_missing_batch_returns_404(self, api, payroll_headers):
        """PRD §2.10: "Existence of every identifier appearing in the path or
        body, validated left to right, each miss producing that resource's
        not-found error: `ERR_PRODUCTION_NOT_FOUND`, `ERR_ACTOR_NOT_FOUND`,
        `ERR_CASTING_CALL_NOT_FOUND`, `ERR_LOOK_REQUIREMENT_NOT_FOUND`,
        `ERR_HOLDING_AREA_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`,
        `ERR_TIME_EVENT_NOT_FOUND`, `ERR_VOUCHER_NOT_FOUND`,
        `ERR_BUMP_ADJUSTMENT_NOT_FOUND`, `ERR_PAYROLL_BATCH_NOT_FOUND`,
        `ERR_REPLACEMENT_CASE_NOT_FOUND`, `ERR_STANDBY_ENTRY_NOT_FOUND`, or
        `ERR_RATIO_WAIVER_NOT_FOUND`."

        Design: Corner/validations/items_on_missing_batch_returns_404
        """
        prod = create_production(active=True)
        batch = create_batch(prod["id"], creator="pc-1")
        res = api.add_batch_item(
            ABSENT_UUID,
            {
                "voucher_id": "00000000-0000-4000-8000-000000000001",
                "expected_batch_version": batch["version"],
            },
            payroll_headers,
        )
        validate_error(res, ApiErrorId.ERR_PAYROLL_BATCH_NOT_FOUND)

    def test_batch_double_submit_rejected(self, api, payroll_headers):
        """PRD §3.8: "The coordinator may submit from `OPEN` or
        `PARTIALLY_REJECTED` (`ERR_BATCH_INVALID_STATE` otherwise)"

        Design: Corner/errors/batch_double_submit_rejected
        """
        _p, _c, _a, _b, _v, batch = setup_submitted_batch(wrap_at="2026-08-10T12:00:00Z")
        assert batch["status"] == "SUBMITTED"
        res = api.submit_batch(batch["id"], payroll_headers)
        validate_error(res, ApiErrorId.ERR_BATCH_INVALID_STATE)


class TestBatchLedger:
    def _walk_add_remove_readd(self, api):
        """OPEN batch + issued voucher (gross 10938): add -> remove -> re-add.
        Returns (voucher_id, batch, added, removed, readded)."""
        prod, call, actor, booking, voucher = setup_issued_voucher(**DAY)
        assert voucher["gross_total_cents"] == 10938
        batch = create_batch(prod["id"], creator="pc-1")

        added = add_batch_item(
            batch["id"], voucher["id"],
            expected_batch_version=batch["version"], operator="pc-1",
        )
        removed = validate_success(
            api.remove_batch_item(
                batch["id"], {"voucher_id": voucher["id"]}, make_payroll_headers("pc-1")
            ),
            200,
        )
        readded = add_batch_item(
            batch["id"], voucher["id"],
            expected_batch_version=removed["version"], operator="pc-1",
        )
        return voucher["id"], batch, added, removed, readded

    def test_batch_gross_ledger_conservation(self, api, payroll_headers):
        """PRD §2.7: "A batch's `gross_total_cents` equals the sum of the
        `gross_total_cents` of the vouchers currently referencing it, and its
        `voucher_count` equals the number of those vouchers; both are recomputed
        after every membership change — an item add, an item removal, a voucher
        dispute that ejects it from the batch, an acknowledgment that rejects
        members, or a bump approval touching a batched voucher."

        Design: Difficulty/compensating_invariant/batch_gross_ledger_conservation
        """
        voucher_id, batch, added, removed, readded = self._walk_add_remove_readd(api)
        assert added["gross_total_cents"] == 10938
        assert added["voucher_count"] == 1
        assert removed["gross_total_cents"] == 0
        assert removed["voucher_count"] == 0
        assert readded["gross_total_cents"] == 10938
        assert readded["voucher_count"] == 1

    def test_batch_ledger_membership_pointer_round_trip(self, api, payroll_headers):
        """PRD §3.8: "A successful add points the voucher's `payroll_batch_id` at
        the batch, recomputes the batch totals, recomputes the production's
        `payroll_exposure_cents`, and increments the batch's `version` by one."
        PRD §3.8: "Removal is the compensating mirror: removing an item from an
        `OPEN` batch clears the voucher's `payroll_batch_id`, recomputes batch
        totals and production exposure, and increments the batch's `version`."

        Design: Difficulty/compensating_invariant/batch_gross_ledger_conservation
        """
        prod, call, actor, booking, voucher = setup_issued_voucher(**DAY)
        batch = create_batch(prod["id"], creator="pc-1")

        added = add_batch_item(
            batch["id"], voucher["id"],
            expected_batch_version=batch["version"], operator="pc-1",
        )
        assert added["version"] == batch["version"] + 1
        after_add = validate_success(api.get_voucher(voucher["id"], payroll_headers), 200)
        assert after_add["payroll_batch_id"] == batch["id"]
        assert_payroll_batch(added)

        removed = validate_success(
            api.remove_batch_item(
                batch["id"], {"voucher_id": voucher["id"]}, make_payroll_headers("pc-1")
            ),
            200,
        )
        assert removed["version"] == added["version"] + 1
        after_remove = validate_success(
            api.get_voucher(voucher["id"], payroll_headers), 200
        )
        assert after_remove["payroll_batch_id"] is None

        readded = add_batch_item(
            batch["id"], voucher["id"],
            expected_batch_version=removed["version"], operator="pc-1",
        )
        assert readded["version"] == removed["version"] + 1
        assert readded["gross_total_cents"] == 10938


class TestDisputeCascade:
    def test_dispute_strips_batch_totals(self, api, payroll_headers):
        """PRD §3.6: "A dispute moves the voucher to `DISPUTED` and, when the
        voucher currently sits in an `OPEN` batch, ejects it: `payroll_batch_id`
        is cleared, the batch's `gross_total_cents` and `voucher_count`
        recompute, the batch's `version` increments, and the production's
        `payroll_exposure_cents` recomputes with its own `version` increment."

        Design: Difficulty/transitive_cascade/dispute_strips_batch_and_exposure
        """
        prod, _c, actor, _b, voucher, batch = setup_open_batch_with_voucher(**DAY)
        assert batch["gross_total_cents"] == 10938
        assert batch["voucher_count"] == 1
        prod_before = validate_success(api.get_production(prod["id"], payroll_headers), 200)
        assert prod_before["payroll_exposure_cents"] == 10938

        disputed = validate_success(
            api.dispute_voucher(
                voucher["id"], {"reason": "rate dispute"},
                make_actor_headers(actor["id"]),
            ),
            200,
        )
        assert disputed["status"] == "DISPUTED"

        batch_after = validate_success(
            api.get_payroll_batch(batch["id"], payroll_headers), 200
        )
        assert batch_after["gross_total_cents"] == 0
        assert batch_after["voucher_count"] == 0

    def test_dispute_clears_membership_and_exposure(self, api, payroll_headers):
        """PRD §3.6: "A dispute moves the voucher to `DISPUTED` and, when the
        voucher currently sits in an `OPEN` batch, ejects it: `payroll_batch_id`
        is cleared, the batch's `gross_total_cents` and `voucher_count`
        recompute, the batch's `version` increments, and the production's
        `payroll_exposure_cents` recomputes with its own `version` increment."
        PRD §2.7: "each production's `payroll_exposure_cents` equals the sum of
        `gross_total_cents` across all of that production's payroll batches and
        is recomputed whenever any batch total changes"

        Design: Difficulty/transitive_cascade/dispute_strips_batch_and_exposure
        """
        prod, _c, actor, _b, voucher, batch = setup_open_batch_with_voucher(**DAY)
        disputed = validate_success(
            api.dispute_voucher(
                voucher["id"], {"reason": "rate dispute"},
                make_actor_headers(actor["id"]),
            ),
            200,
        )
        assert disputed["status"] == "DISPUTED"
        assert disputed["payroll_batch_id"] is None

        prod_after = validate_success(api.get_production(prod["id"], payroll_headers), 200)
        assert prod_after["payroll_exposure_cents"] == 0


class TestAcknowledgment:
    def test_sod_batch_self_acknowledge_rejected(self, api):
        """PRD §2.1: "The operator who records a payroll company's acknowledgment
        of a batch must not be the operator who submitted that batch, or the
        acknowledgment is rejected with `ERR_SOD_SELF_ACKNOWLEDGE` (HTTP 403)."
        PRD §3.8: "An `ACCEPTED` outcome with an empty rejection list moves the
        batch to `ACKNOWLEDGED` — terminal — and every member voucher to `PAID`"

        Design: Corner/rbac/sod_batch_self_acknowledge_rejected
        """
        _p, _c, _a, _b, voucher, batch = setup_submitted_batch(
            operator="pc-1", wrap_at="2026-08-10T12:00:00Z"
        )
        assert batch["status"] == "SUBMITTED"
        assert batch["submitted_by_user_id"] == "pc-1"

        res = api.acknowledge_batch(
            batch["id"], {"outcome": "ACCEPTED"}, make_payroll_headers("pc-1")
        )
        validate_error(res, ApiErrorId.ERR_SOD_SELF_ACKNOWLEDGE)
        batch_mid = validate_success(
            api.get_payroll_batch(batch["id"], make_payroll_headers("pc-1")), 200
        )
        assert batch_mid["status"] == "SUBMITTED"

        acked = validate_success(
            api.acknowledge_batch(
                batch["id"], {"outcome": "ACCEPTED"}, make_payroll_headers("pc-2")
            ),
            200,
        )
        assert acked["status"] == "ACKNOWLEDGED"
        assert acked["acknowledged_by_user_id"] == "pc-2"
        voucher_after = validate_success(
            api.get_voucher(voucher["id"], make_payroll_headers("pc-1")), 200
        )
        assert voucher_after["status"] == "PAID"

    def test_payroll_batch_rejection_resubmission_cycle(self, api):
        """PRD §3.8: "A `REJECTED` outcome with a non-empty list first verifies
        that every listed id is a `SUBMITTED` member of this batch
        (`ERR_VOUCHER_NOT_SUBMITTABLE` otherwise), then moves the listed vouchers
        to `REJECTED`, ejects them from the batch with their `payroll_batch_id`
        cleared, recomputes the batch's `gross_total_cents` and `voucher_count`,
        recomputes the production's `payroll_exposure_cents`, and lands the batch
        in `PARTIALLY_REJECTED`."
        PRD §3.8: "adding into a `PARTIALLY_REJECTED` batch deliberately returns
        it to `OPEN` for re-editing, incrementing `version`."

        Design: Corner/state_machines/payroll_batch_rejection_resubmission_cycle
        """
        _p, _c, _a, _b, voucher, batch = setup_submitted_batch(operator="pc-1", **DAY)

        rejected = validate_success(
            api.acknowledge_batch(
                batch["id"],
                {"outcome": "REJECTED", "rejected_voucher_ids": [voucher["id"]]},
                make_payroll_headers("pc-2"),
            ),
            200,
        )
        assert rejected["status"] == "PARTIALLY_REJECTED"
        assert rejected["gross_total_cents"] == 0
        assert rejected["voucher_count"] == 0

        voucher_mid = validate_success(
            api.get_voucher(voucher["id"], make_payroll_headers("pc-1")), 200
        )
        assert voucher_mid["status"] == "REJECTED"
        assert voucher_mid["payroll_batch_id"] is None

        adjusted = validate_success(
            api.adjust_voucher(
                voucher["id"],
                {"expected_voucher_version": voucher_mid["version"]},
                TEST_USERS["associate_headers"],
            ),
            200,
        )
        assert adjusted["status"] == "ISSUED"

        readded = add_batch_item(
            batch["id"], voucher["id"],
            expected_batch_version=rejected["version"], operator="pc-1",
        )
        assert readded["status"] == "OPEN"
        assert readded["gross_total_cents"] == 10938

        resubmitted = submit_batch(batch["id"], operator="pc-1")
        assert resubmitted["status"] == "SUBMITTED"

        acked = validate_success(
            api.acknowledge_batch(
                batch["id"], {"outcome": "ACCEPTED"}, make_payroll_headers("pc-2")
            ),
            200,
        )
        assert acked["status"] == "ACKNOWLEDGED"
        voucher_final = validate_success(
            api.get_voucher(voucher["id"], make_payroll_headers("pc-1")), 200
        )
        assert voucher_final["status"] == "PAID"


class TestBatchOCC:
    def test_occ_stale_batch_version_rejected(self, api, payroll_headers):
        """PRD §2.9: "Adding a voucher to a payroll batch requires the request to
        carry `expected_batch_version`, holding the batch `version` the client
        last observed. If the batch's current `version` has advanced past that
        value — because another add, a removal, a dispute ejection, a bump
        approval, or an acknowledgment touched it in the meantime — the add is
        rejected with `ERR_STALE_BATCH_VERSION` (HTTP 412)"

        Design: Corner/cross_cutting_complexity_layers/occ_stale_batch_version_rejected
        """
        prod, _c, _a, _b, voucher = setup_issued_voucher(wrap_at="2026-08-10T12:00:00Z")
        batch = create_batch(prod["id"], creator="pc-1")
        stale_version = batch["version"]

        added = add_batch_item(
            batch["id"], voucher["id"],
            expected_batch_version=stale_version, operator="pc-1",
        )
        assert added["version"] > stale_version

        res = api.add_batch_item(
            batch["id"],
            {"voucher_id": voucher["id"], "expected_batch_version": stale_version},
            payroll_headers,
        )
        validate_error(res, ApiErrorId.ERR_STALE_BATCH_VERSION)
