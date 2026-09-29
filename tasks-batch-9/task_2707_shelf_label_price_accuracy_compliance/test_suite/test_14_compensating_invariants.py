"""Forward operations and their compensations, checked for drift at every checkpoint."""

from test_helpers import (
    assert_instant_is,
    assert_money_cents,
    assert_pct,
    factories,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_ACTION_INVALID_STATE,
    ERR_ASSOCIATE_INVALID_STATE,
    ERR_REFUND_CLAIM_INVALID_STATE,
    ERR_REFUND_NOT_APPROVED,
    ERR_TRAINING_SCORE_TOO_LOW,
    ERR_TRANSITION_ALREADY_APPLIED,
    ERR_VOID_REASON_REQUIRED,
)
from test_helpers.constants import (
    ROLE_CODE_LABEL_ASSOCIATE,
    ROLE_CODE_PRICE_AUDITOR,
    ROLE_CODE_STORE_MANAGER,
)


def _ledger(build, store_id):
    """The two mirrored money accumulators, read off the store projection."""
    store = build.read_store(store_id)
    return (
        store["refund_liability_outstanding_cents"],
        store["refund_paid_total_cents"],
    )


def _claim_sum(api, headers, store_id, status):
    """The claimed-amount sum and row count for one store-and-status slice."""
    rows, meta = validate_paginated(
        api.list_refund_claims(headers, {"store_id": store_id, "status": status})
    )
    return sum(row["claimed_amount_cents"] for row in rows), meta["total_count"]


class TestRefundLedgerReconciles:
    def test_pay_moves_the_money_between_accumulators_and_deny_takes_it_off_both(
        self, api, build, desk_headers
    ):
        """Two mirrored sums, checked after every settlement, with approval a deliberate no-op.

        PRD 2.7: "Everything else on a store is derived: a store never accepts a direct
        write to any counter, and every counter is recomputed from the underlying rows
        rather than adjusted by a delta, so that forward operations and their
        compensating operations cannot drift apart."
        PRD 2.7: "`refund_liability_outstanding_cents` is the sum of the claimed
        amounts of this store's refund claims whose status is `PENDING` or `APPROVED`."
        PRD 2.7: "`refund_paid_total_cents` is the sum of the claimed amounts of this
        store's claims whose status is `PAID`."
        PRD 3.8: "Under `REFUND_DIFFERENCE_PLUS_FIXED` the gross amount is the variance
        plus the jurisdiction's `refund_fixed_bonus_cents` goodwill payment."
        PRD 3.8: "A store manager approves a `PENDING` claim, moving it `PENDING →
        APPROVED`; the store's outstanding liability is unchanged by approval, because
        `PENDING` and `APPROVED` are both outstanding."
        PRD 3.8: "A customer service desk operator pays an `APPROVED` claim, moving it
        `APPROVED → PAID`, stamping `paid_at` with the current instant, and recomputing
        both the store's `refund_liability_outstanding_cents` — from which the amount
        now leaves — and its `refund_paid_total_cents`, into which the amount now
        enters."
        PRD 3.8: "A store manager denies a claim, moving it to `DENIED` from either
        `PENDING` or `APPROVED` — the two source states behave identically — storing
        the `denial_reason` and recomputing the store's
        `refund_liability_outstanding_cents`, from which this claim's amount now
        departs."

        Design: Difficulty/compensating_invariant/refund_liability_ledger_reconciles_across_approve_pay_and_deny
        """
        jurisdiction_id = build.jurisdiction(
            code="US-CA",
            overcharge_refund_policy="REFUND_DIFFERENCE_PLUS_FIXED",
            refund_fixed_bonus_cents=500,
            refund_cap_cents=5000,
            refund_budget_per_audit_cents=100000,
            scanner_error_rate_threshold_pct=60.0,
        )
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        aisle_id = build.aisle(store_id, aisle_code="A01", category_code="DAIRY")
        auditor_id = build.certified(
            store_id,
            ROLE_CODE_PRICE_AUDITOR,
            module_code="AUDIT_101",
            employee_number="E-PA1",
            full_name="Pat Auditor",
        )
        manager_id = build.certified(
            store_id,
            ROLE_CODE_STORE_MANAGER,
            employee_number="E-SM1",
            full_name="Sam Manager",
        )
        manager_headers = build.manager(manager_id)

        evidence = build.audit_with_scan_lines(
            store_id,
            aisle_id,
            auditor_id,
            [
                {"item_upc": "00000000001501", "shelf_price_cents": 949, "register_price_cents": 1099},
                {"item_upc": "00000000001502", "shelf_price_cents": 349, "register_price_cents": 599},
                {"item_upc": "00000000001503", "shelf_price_cents": 199, "register_price_cents": 1099},
                {"item_upc": "00000000001504", "shelf_price_cents": 299, "register_price_cents": 299},
                {"item_upc": "00000000001505", "shelf_price_cents": 259, "register_price_cents": 259},
            ],
        )
        closed = build.close_audit(
            evidence["audit_id"], build.auditor(auditor_id), "GROSS_MISMATCH"
        )
        assert closed["status"] == "CLOSED"
        assert closed["sample_size"] == 5
        assert closed["overcharge_count"] == 3
        assert_pct(closed["gross_error_rate_pct"], 60.00)
        assert closed["outcome"] == "FAIL"
        audit_version = closed["version"]
        lines = evidence["scan_line_ids"]

        assert _ledger(build, store_id) == (0, 0)

        claim_a = build.refund_claim(lines[0], "CUST-A", audit_version, desk_headers)
        assert_money_cents(claim_a["claimed_amount_cents"], 650)
        assert claim_a["status"] == "PENDING"
        assert claim_a["denial_reason"] is None
        assert claim_a["paid_at"] is None
        assert claim_a["store_id"] == store_id
        assert _ledger(build, store_id) == (650, 0)

        claim_b = build.refund_claim(lines[1], "CUST-B", audit_version, desk_headers)
        assert_money_cents(claim_b["claimed_amount_cents"], 750)
        assert _ledger(build, store_id) == (1400, 0)

        approved = build.settle_claim(claim_a["id"], "APPROVED", manager_headers)
        assert approved["status"] == "APPROVED"
        assert _ledger(build, store_id) == (1400, 0)
        assert _claim_sum(api, desk_headers, store_id, "PENDING")[0] == 750
        assert _claim_sum(api, desk_headers, store_id, "APPROVED")[0] == 650

        paid = build.settle_claim(claim_a["id"], "PAID", desk_headers)
        assert paid["status"] == "PAID"
        assert_instant_is(paid["paid_at"], "2026-08-01T00:00:00Z")
        assert _ledger(build, store_id) == (750, 650)

        denied = build.settle_claim(
            claim_b["id"],
            "DENIED",
            manager_headers,
            denial_reason="Customer could not produce the receipt",
        )
        assert denied["status"] == "DENIED"
        assert denied["denial_reason"] == "Customer could not produce the receipt"
        assert _ledger(build, store_id) == (0, 650)

        claim_c = build.refund_claim(
            lines[2], "CUST-C", build.audit_version(evidence["audit_id"]), desk_headers
        )
        assert_money_cents(claim_c["claimed_amount_cents"], 1400)
        assert _ledger(build, store_id) == (1400, 650)

        build.settle_claim(
            claim_c["id"],
            "DENIED",
            manager_headers,
            denial_reason="Duplicate of an earlier goodwill credit",
        )
        assert _ledger(build, store_id) == (0, 650)

        pending_sum, pending_count = _claim_sum(api, desk_headers, store_id, "PENDING")
        approved_sum, approved_count = _claim_sum(api, desk_headers, store_id, "APPROVED")
        paid_sum, paid_count = _claim_sum(api, desk_headers, store_id, "PAID")
        assert (pending_count, approved_count, paid_count) == (0, 0, 1)
        assert pending_sum + approved_sum == 0
        assert paid_sum == 650
        assert 650 + 750 + 1400 == 2800

        rows, meta = validate_paginated(
            api.list_refund_claims(desk_headers, {"store_id": store_id})
        )
        assert meta["total_count"] == 3
        assert sorted(row["status"] for row in rows) == ["DENIED", "DENIED", "PAID"]
        assert build.read_summary(store_id)["refund_liability_outstanding_cents"] == 0

    def test_the_two_stores_keep_separate_books_and_a_refused_settlement_moves_nothing(
        self, api, build, desk_headers
    ):
        """Each ledger is per store and per claim state; three refusals leave both sums untouched.

        PRD 3.8: "The claim's `store_id` is never supplied by the client: it is resolved
        server-side from the scan line's owning audit at creation, so a claim can never
        be attributed to the wrong store."
        PRD 3.8: "Under `ITEM_FREE_UP_TO_CAP` the customer keeps the item, so the gross
        amount is the full `register_price_cents` the customer was charged."
        PRD 3.8: "In all three branches the amount finally stored as
        `claimed_amount_cents` is the smaller of the gross amount and the
        jurisdiction's `refund_cap_cents`; the cap is applied last and is inclusive, so
        a gross amount exactly equal to the cap is paid in full."
        PRD 3.8: "A store manager denies a claim, moving it to `DENIED` from either
        `PENDING` or `APPROVED` — the two source states behave identically — storing
        the `denial_reason` and recomputing the store's
        `refund_liability_outstanding_cents`, from which this claim's amount now
        departs."
        PRD 3.8: "Requesting payment on a claim whose status is anything other than
        `APPROVED` is refused with `ERR_REFUND_NOT_APPROVED`; any other disallowed
        settlement transition, such as approving a denied claim or denying a paid one,
        is refused with `ERR_REFUND_CLAIM_INVALID_STATE`; and repeating a settlement
        that has already been applied, such as paying an already-`PAID` claim, is
        refused with `ERR_TRANSITION_ALREADY_APPLIED`."
        PRD 2.7: "`refund_liability_outstanding_cents` is the sum of the claimed
        amounts of this store's refund claims whose status is `PENDING` or `APPROVED`."
        PRD 2.7: "`refund_paid_total_cents` is the sum of the claimed amounts of this
        store's claims whose status is `PAID`."

        Design: Difficulty/compensating_invariant/refund_liability_ledger_reconciles_across_approve_pay_and_deny
        """
        jurisdiction_id = build.jurisdiction(
            code="US-CA",
            overcharge_refund_policy="ITEM_FREE_UP_TO_CAP",
            refund_cap_cents=1000,
            refund_budget_per_audit_cents=100000,
            scanner_error_rate_threshold_pct=60.0,
        )
        store_a = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        store_b = build.store(jurisdiction_id, store_number="S002", name="Mission Row")
        aisle_a = build.aisle(store_a, aisle_code="A01", category_code="DAIRY")
        aisle_b = build.aisle(store_b, aisle_code="A01", category_code="DAIRY")
        pa_a = build.certified(
            store_a,
            ROLE_CODE_PRICE_AUDITOR,
            module_code="AUDIT_101",
            employee_number="E-PA1",
            full_name="Pat Auditor",
        )
        pa_b = build.certified(
            store_b,
            ROLE_CODE_PRICE_AUDITOR,
            module_code="AUDIT_101",
            employee_number="E-PA2",
            full_name="Paula Auditor",
        )
        sm_a = build.certified(
            store_a,
            ROLE_CODE_STORE_MANAGER,
            employee_number="E-SM1",
            full_name="Sam Manager",
        )
        sm_b = build.certified(
            store_b,
            ROLE_CODE_STORE_MANAGER,
            employee_number="E-SM2",
            full_name="Sara Manager",
        )
        manager_a = build.manager(sm_a)
        manager_b = build.manager(sm_b)

        evidence_a = build.audit_with_scan_lines(
            store_a,
            aisle_a,
            pa_a,
            [
                {"item_upc": "00000000001601", "shelf_price_cents": 949, "register_price_cents": 1099},
                {"item_upc": "00000000001602", "shelf_price_cents": 700, "register_price_cents": 800},
            ],
        )
        closed_a = build.close_audit(
            evidence_a["audit_id"], build.auditor(pa_a), "GROSS_MISMATCH"
        )
        assert closed_a["status"] == "CLOSED"
        evidence_b = build.audit_with_scan_lines(
            store_b,
            aisle_b,
            pa_b,
            [
                {"item_upc": "00000000001603", "shelf_price_cents": 500, "register_price_cents": 600},
            ],
        )
        closed_b = build.close_audit(
            evidence_b["audit_id"], build.auditor(pa_b), "GROSS_MISMATCH"
        )
        assert closed_b["status"] == "CLOSED"

        assert _ledger(build, store_a) == (0, 0)
        assert _ledger(build, store_b) == (0, 0)

        capped = build.refund_claim(
            evidence_a["scan_line_ids"][0], "CUST-A1", closed_a["version"], desk_headers
        )
        assert_money_cents(capped["claimed_amount_cents"], 1000)
        assert capped["store_id"] == store_a
        assert capped["policy_applied"] == "ITEM_FREE_UP_TO_CAP"
        assert _ledger(build, store_a) == (1000, 0)
        assert _ledger(build, store_b) == (0, 0)

        uncapped = build.refund_claim(
            evidence_a["scan_line_ids"][1], "CUST-A2", closed_a["version"], desk_headers
        )
        assert_money_cents(uncapped["claimed_amount_cents"], 800)
        assert _ledger(build, store_a) == (1800, 0)

        neighbour = build.refund_claim(
            evidence_b["scan_line_ids"][0], "CUST-B1", closed_b["version"], desk_headers
        )
        assert_money_cents(neighbour["claimed_amount_cents"], 600)
        assert neighbour["store_id"] == store_b
        assert _ledger(build, store_b) == (600, 0)
        assert _ledger(build, store_a) == (1800, 0)

        assert build.settle_claim(capped["id"], "APPROVED", manager_a)["status"] == "APPROVED"
        assert _ledger(build, store_a) == (1800, 0)
        denied_from_approved = build.settle_claim(
            capped["id"],
            "DENIED",
            manager_a,
            denial_reason="Register journal showed the promotion had ended",
        )
        assert denied_from_approved["status"] == "DENIED"
        assert _ledger(build, store_a) == (800, 0)

        validate_error(
            api.settle_refund_claim(
                uncapped["id"], factories.settle_claim_payload("PAID"), desk_headers
            ),
            ERR_REFUND_NOT_APPROVED,
            409,
        )
        assert build.read_claim(uncapped["id"])["status"] == "PENDING"
        assert _ledger(build, store_a) == (800, 0)

        validate_error(
            api.settle_refund_claim(
                capped["id"], factories.settle_claim_payload("APPROVED"), manager_a
            ),
            ERR_REFUND_CLAIM_INVALID_STATE,
            409,
        )
        assert build.read_claim(capped["id"])["status"] == "DENIED"
        assert _ledger(build, store_a) == (800, 0)

        build.settle_claim(uncapped["id"], "APPROVED", manager_a)
        paid = build.settle_claim(uncapped["id"], "PAID", desk_headers)
        assert paid["status"] == "PAID"
        assert _ledger(build, store_a) == (0, 800)
        validate_error(
            api.settle_refund_claim(
                uncapped["id"], factories.settle_claim_payload("PAID"), desk_headers
            ),
            ERR_TRANSITION_ALREADY_APPLIED,
            409,
        )
        assert _ledger(build, store_a) == (0, 800)

        build.settle_claim(neighbour["id"], "APPROVED", manager_b)
        assert build.settle_claim(neighbour["id"], "PAID", desk_headers)["status"] == "PAID"
        assert _ledger(build, store_b) == (0, 600)
        assert _ledger(build, store_a) == (0, 800)

        assert _claim_sum(api, desk_headers, store_a, "PAID") == (800, 1)
        assert _claim_sum(api, desk_headers, store_b, "PAID") == (600, 1)
        assert _claim_sum(api, desk_headers, store_a, "PENDING") == (0, 0)
        rows_a, meta_a = validate_paginated(
            api.list_refund_claims(desk_headers, {"store_id": store_a})
        )
        assert meta_a["total_count"] == 2
        assert sorted(row["status"] for row in rows_a) == ["DENIED", "PAID"]
        rows_b, meta_b = validate_paginated(
            api.list_refund_claims(desk_headers, {"store_id": store_b})
        )
        assert meta_b["total_count"] == 1
        assert rows_b[0]["id"] == neighbour["id"]


def _counted_backlog(api, build, headers, store_id):
    """The backlog recounted from the task list, skipping tasks on withdrawn lines."""
    counted = 0
    for placement_status in ("UNPLACED", "REJECTED"):
        rows, _meta = validate_paginated(
            api.list_label_tasks(
                headers, {"store_id": store_id, "placement_status": placement_status}
            )
        )
        for row in rows:
            line = build.read_line(row["price_change_line_id"])
            if line["line_status"] != "WITHDRAWN":
                counted += 1
    return counted


TWO_DAIRY_LINES = [
    {"item_upc": "00000000001601", "item_description": "Milk 1gal", "category_code": "DAIRY",
     "old_retail_cents": 449, "new_retail_cents": 399, "net_content_qty": 1, "net_content_uom": "GAL"},
    {"item_upc": "00000000001602", "item_description": "Butter 1lb", "category_code": "DAIRY",
     "old_retail_cents": 549, "new_retail_cents": 499, "net_content_qty": 1, "net_content_uom": "LB"},
]


class TestLabelBacklogCounter:
    def test_place_reject_place_leaves_no_drift_and_a_supersede_empties_the_backlog(
        self, api, build, admin_headers
    ):
        """The counter walks 2 to 1 to 2 to 1 and then to 0 through a change on the line, not the task.

        PRD 2.7: "`label_backlog_count` is the number of this store's label tasks whose
        placement axis is `UNPLACED` or `REJECTED` **and** whose underlying price change
        line is not `WITHDRAWN`."
        PRD 2.7: "There is no time window on this count; it is a full recompute from
        scratch on every trigger, and its triggers are label-task creation, every
        placement-axis transition, the withdrawal cascade that follows a supersede, and
        the cascade that fires when a price change file becomes fully executed."
        PRD 3.4: "The placement axis is untouched by printing."
        PRD 3.4: "On success, `placed_by_associate_id` is stamped from `X-User-ID` and
        `placed_at` from the current instant, the store's label backlog is recomputed
        and then its posture recomputed, and when the underlying line sits in `FAILED`
        it moves `FAILED → LABELED`."
        PRD 3.4: "It increments `rejection_count` by one, pushes the print axis from
        `PRINTED` back to `REPRINT_REQUIRED`, and pushes the underlying line `LABELED →
        FAILED`."
        PRD 3.3: "Every line of the batch whose status is not `VERIFIED` — that is,
        every line still in `PENDING`, `TASKED`, `LABELED` or `FAILED` — transitions to
        `WITHDRAWN`, and a withdrawn line permanently leaves every store's label
        backlog."
        PRD 3.3: "For each withdrawn line, every label task on it whose placement axis
        is not `VERIFIED` has its print axis forced to `REPRINT_REQUIRED` with its
        `printed_label_serial` cleared, because the tag in the printer's tray now shows
        a price nobody is allowed to charge."

        Design: Difficulty/compensating_invariant/label_backlog_counter_survives_reject_replace_and_withdrawal
        """
        jurisdiction_id = build.jurisdiction(code="US-CA", grace_period_hours=48)
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        aisle_id = build.aisle(store_id, aisle_code="A01", category_code="DAIRY")
        la1 = build.certified(
            store_id,
            ROLE_CODE_LABEL_ASSOCIATE,
            employee_number="E-LA1",
            full_name="Lena Label",
        )
        pa1 = build.certified(
            store_id,
            ROLE_CODE_PRICE_AUDITOR,
            module_code="AUDIT_101",
            employee_number="E-PA1",
            full_name="Pat Auditor",
        )
        built = build.distributed_file(
            jurisdiction_id,
            [store_id],
            TWO_DAIRY_LINES,
            effective_date="2026-08-03T00:00:00Z",
            file_number="PCF-1001",
        )
        replacement = build.price_change_file(
            jurisdiction_id,
            [store_id],
            effective_date="2026-08-04T00:00:00Z",
            file_number="PCF-1002",
        )
        assert replacement["status"] == "DRAFT"
        line_1, line_2 = built["line_ids"]
        task_1 = build.label_task(
            built["file_id"],
            store_id,
            line_1,
            aisle_id,
            la1,
            scheduled_start_at="2026-08-03T09:00:00Z",
            scheduled_end_at="2026-08-03T10:00:00Z",
        )
        task_2 = build.label_task(
            built["file_id"],
            store_id,
            line_2,
            aisle_id,
            la1,
            scheduled_start_at="2026-08-03T10:01:00Z",
            scheduled_end_at="2026-08-03T11:00:00Z",
        )
        la1_headers = build.associate_headers(la1)

        baseline = build.read_store(store_id)
        assert baseline["label_backlog_count"] == 2
        assert baseline["compliance_posture"] == "OPEN"
        assert _counted_backlog(api, build, admin_headers, store_id) == 2

        printed = build.print_task(task_1["id"], la1_headers)
        assert printed["print_status"] == "PRINTED"
        assert printed["placement_status"] == "UNPLACED"
        assert build.read_store(store_id)["label_backlog_count"] == 2
        assert _counted_backlog(api, build, admin_headers, store_id) == 2

        placed = build.place_task(task_1["id"], 399, la1_headers)
        assert placed["placement_status"] == "PLACED"
        assert build.read_store(store_id)["label_backlog_count"] == 1
        assert _counted_backlog(api, build, admin_headers, store_id) == 1

        rejected = build.verify_task(
            task_1["id"],
            build.auditor(pa1),
            outcome="REJECTED",
            rejection_reason="Tag was placed on the adjacent facing",
        )
        assert rejected["placement_status"] == "REJECTED"
        assert rejected["print_status"] == "REPRINT_REQUIRED"
        assert rejected["rejection_count"] == 1
        assert build.read_line(line_1)["line_status"] == "FAILED"
        assert build.read_store(store_id)["label_backlog_count"] == 2
        assert _counted_backlog(api, build, admin_headers, store_id) == 2

        build.print_task(task_1["id"], la1_headers)
        replaced = build.place_task(task_1["id"], 399, la1_headers)
        assert replaced["placement_status"] == "PLACED"
        assert build.read_line(line_1)["line_status"] == "LABELED"
        assert build.read_store(store_id)["label_backlog_count"] == 1
        assert _counted_backlog(api, build, admin_headers, store_id) == 1

        superseded = validate_success(
            api.supersede_price_change_file(
                built["file_id"],
                factories.supersede_payload(replacement["id"]),
                build.admin,
            )
        )
        assert superseded["status"] == "SUPERSEDED"
        assert superseded["superseded_by_file_id"] == replacement["id"]
        assert build.read_line(line_1)["line_status"] == "WITHDRAWN"
        assert build.read_line(line_2)["line_status"] == "WITHDRAWN"

        after_1 = build.read_task(task_1["id"])
        after_2 = build.read_task(task_2["id"])
        assert after_1["placement_status"] == "PLACED"
        assert after_2["placement_status"] == "UNPLACED"
        assert after_1["print_status"] == "REPRINT_REQUIRED"
        assert after_2["print_status"] == "REPRINT_REQUIRED"
        assert after_1["printed_label_serial"] is None

        final_store = build.read_store(store_id)
        assert final_store["label_backlog_count"] == 0
        assert final_store["compliance_posture"] == "OPEN"
        assert _counted_backlog(api, build, admin_headers, store_id) == 0
        assert build.read_summary(store_id)["label_backlog_count"] == 0

    def test_the_counter_drives_the_posture_across_the_restricted_edge_without_drift(
        self, api, build, admin_headers
    ):
        """Five outstanding tags restrict the store; the reject-replace round trip returns it exactly.

        PRD 2.7: "`label_backlog_count` is the number of this store's label tasks whose
        placement axis is `UNPLACED` or `REJECTED` **and** whose underlying price change
        line is not `WITHDRAWN`."
        PRD 2.7: "Otherwise the posture becomes `RESTRICTED` when the open finding count
        is at least 1, **or** when the thirty-day failed-audit count is exactly 1,
        **or** when the label backlog is at least 5, **or** when at least one signage
        violation exists."
        PRD 2.7: "If none of those hold, the posture is `OPEN`."
        PRD 3.4: "On success, `placed_by_associate_id` is stamped from `X-User-ID` and
        `placed_at` from the current instant, the store's label backlog is recomputed
        and then its posture recomputed, and when the underlying line sits in `FAILED`
        it moves `FAILED → LABELED`."
        PRD 3.4: "It increments `rejection_count` by one, pushes the print axis from
        `PRINTED` back to `REPRINT_REQUIRED`, and pushes the underlying line `LABELED →
        FAILED`."
        PRD 3.3: "A batch in `PARTIALLY_EXECUTED` advances `PARTIALLY_EXECUTED →
        EXECUTED` the moment a line's move into `VERIFIED` makes the verified-line count
        equal the line count, provided the line count is at least 1."
        PRD 3.3: "On completion, every store named in the batch's `scope_store_ids` has
        its `executed_file_count` raised by one, then its label backlog recomputed, then
        its posture recomputed, in that order."

        Design: Difficulty/compensating_invariant/label_backlog_counter_survives_reject_replace_and_withdrawal
        """
        jurisdiction_id = build.jurisdiction(code="US-CA", grace_period_hours=48)
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        aisle_id = build.aisle(store_id, aisle_code="A01", category_code="DAIRY")
        la1 = build.certified(
            store_id,
            ROLE_CODE_LABEL_ASSOCIATE,
            employee_number="E-LA1",
            full_name="Lena Label",
        )
        pa1 = build.certified(
            store_id,
            ROLE_CODE_PRICE_AUDITOR,
            module_code="AUDIT_101",
            employee_number="E-PA1",
            full_name="Pat Auditor",
        )
        five_lines = [
            {
                "item_upc": f"0000000000170{index}",
                "item_description": f"Dairy item {index}",
                "category_code": "DAIRY",
                "old_retail_cents": 449,
                "new_retail_cents": 399,
                "net_content_qty": 1,
                "net_content_uom": "EACH",
            }
            for index in range(1, 6)
        ]
        built = build.distributed_file(
            jurisdiction_id,
            [store_id],
            five_lines,
            effective_date="2026-08-03T00:00:00Z",
            file_number="PCF-1001",
        )
        windows = [
            ("2026-08-03T00:00:00Z", "2026-08-03T01:00:00Z"),
            ("2026-08-03T01:01:00Z", "2026-08-03T02:00:00Z"),
            ("2026-08-03T02:01:00Z", "2026-08-03T03:00:00Z"),
            ("2026-08-03T03:01:00Z", "2026-08-03T04:00:00Z"),
            ("2026-08-03T04:01:00Z", "2026-08-03T05:00:00Z"),
        ]
        tasks = [
            build.label_task(
                built["file_id"],
                store_id,
                line_id,
                aisle_id,
                la1,
                scheduled_start_at=window[0],
                scheduled_end_at=window[1],
            )
            for line_id, window in zip(built["line_ids"], windows)
        ]
        la1_headers = build.associate_headers(la1)
        pa1_headers = build.auditor(pa1)

        baseline = build.read_store(store_id)
        assert baseline["label_backlog_count"] == 5
        assert baseline["compliance_posture"] == "RESTRICTED"
        assert _counted_backlog(api, build, admin_headers, store_id) == 5

        build.print_task(tasks[0]["id"], la1_headers)
        build.place_task(tasks[0]["id"], 399, la1_headers)
        after_place = build.read_store(store_id)
        assert after_place["label_backlog_count"] == 4
        assert after_place["compliance_posture"] == "OPEN"

        rejected = build.verify_task(
            tasks[0]["id"],
            pa1_headers,
            outcome="REJECTED",
            rejection_reason="Tag showed the old retail",
        )
        assert rejected["rejection_count"] == 1
        after_reject = build.read_store(store_id)
        assert after_reject["label_backlog_count"] == 5
        assert after_reject["compliance_posture"] == "RESTRICTED"
        assert _counted_backlog(api, build, admin_headers, store_id) == 5

        build.print_task(tasks[0]["id"], la1_headers)
        build.place_task(tasks[0]["id"], 399, la1_headers)
        after_replace = build.read_store(store_id)
        assert after_replace["label_backlog_count"] == 4
        assert after_replace["compliance_posture"] == "OPEN"

        verified = build.verify_task(tasks[0]["id"], pa1_headers)
        assert verified["placement_status"] == "VERIFIED"
        assert verified["rejection_count"] == 1
        after_verify = build.read_store(store_id)
        assert after_verify["label_backlog_count"] == 4
        assert after_verify["compliance_posture"] == "OPEN"
        assert after_verify["executed_file_count"] == 0
        assert build.read_file(built["file_id"])["status"] == "PARTIALLY_EXECUTED"

        for task in tasks[1:]:
            build.print_task(task["id"], la1_headers)
            build.place_task(task["id"], 399, la1_headers)
            build.verify_task(task["id"], pa1_headers)

        completed_file = build.read_file(built["file_id"])
        assert completed_file["status"] == "EXECUTED"
        assert completed_file["line_count"] == 5
        assert completed_file["verified_line_count"] == 5
        final_store = build.read_store(store_id)
        assert final_store["label_backlog_count"] == 0
        assert final_store["executed_file_count"] == 1
        assert final_store["compliance_posture"] == "OPEN"
        assert _counted_backlog(api, build, admin_headers, store_id) == 0
        assert build.read_summary(store_id)["label_backlog_count"] == 0


class TestAccountabilityScoreRestored:
    def test_voiding_returns_the_score_bit_for_bit_while_the_suspension_needs_its_own_undo(
        self, api, build, officer_headers, admin_headers
    ):
        """Three issues, two voids, and a remedial completion: the scalar reverses, the state does not.

        PRD 3.2: "Only actions whose status is `ISSUED` count; `COMPLETED` and `VOIDED`
        actions never do."
        PRD 3.2: "The weight assigned to an action by its `action_type` is 5 for
        `COACHING`, 10 for `RETRAINING_ASSIGNED`, 15 for `WRITTEN_WARNING` and 25 for
        `SUSPENSION`, and that weight is stored on the action itself as `score_weight`."
        PRD 3.2: "Under `OCCURRENCE_WEIGHTED`, the score is 100 reduced by the sum of
        the weights of the outstanding actions, floored at zero — each issued action
        costs its flat weight regardless of how much correct work the associate has
        done."
        PRD 3.2: "The suspension floor is 80, and the comparison is **strict**: a
        recomputed score of exactly 80 does not suspend, a score of 79.99 does."
        PRD 3.2: "Alternatively a store manager or compliance officer voids it,
        supplying `target_status` of `VOIDED` together with a `void_reason`; voiding is
        the compensating operation for the accountability-score invariant, and after it
        the score returns to **exactly** its pre-issue value."
        PRD 3.2: "Voiding never changes `training_status`, so voiding the action that
        caused a suspension does not by itself reinstate the associate."
        PRD 3.2: "A qualifying remedial completion applies three compensating effects in
        order: first, every accountability action against this associate whose status is
        `ISSUED` and whose `action_type` is `SUSPENSION` or `RETRAINING_ASSIGNED`
        transitions `ISSUED → COMPLETED`; second, the `accountability_score` is
        recomputed from the actions that remain `ISSUED`; third,
        `certification_expires_at` is re-stamped at the current instant plus 365 days."

        Design: Difficulty/compensating_invariant/accountability_score_returns_to_its_pre_issue_value_after_voids
        """
        jurisdiction_id = build.jurisdiction(
            code="US-CA", accountability_variant="OCCURRENCE_WEIGHTED"
        )
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        la1 = build.certified(
            store_id,
            ROLE_CODE_LABEL_ASSOCIATE,
            employee_number="E-LA1",
            full_name="Lena Label",
        )
        baseline = build.read_associate(la1)
        assert_pct(baseline["accountability_score"], 100.00)
        assert baseline["issued_action_count"] == 0
        assert baseline["training_status"] == "CERTIFIED"
        assert_instant_is(baseline["certification_expires_at"], "2027-08-01T00:00:00Z")

        first_coaching = validate_success(
            api.create_accountability_action(
                la1,
                factories.accountability_action_payload("COACHING", "VERIFICATION_REJECTED"),
                officer_headers,
            ),
            201,
        )
        assert first_coaching["status"] == "ISSUED"
        assert first_coaching["score_weight"] == 5
        after_first = build.read_associate(la1)
        assert_pct(after_first["accountability_score"], 95.00)
        assert after_first["issued_action_count"] == 1
        assert after_first["training_status"] == "CERTIFIED"

        warning = validate_success(
            api.create_accountability_action(
                la1,
                factories.accountability_action_payload("WRITTEN_WARNING", "AUDIT_FAIL"),
                officer_headers,
            ),
            201,
        )
        assert warning["score_weight"] == 15
        on_the_floor = build.read_associate(la1)
        assert_pct(on_the_floor["accountability_score"], 80.00)
        assert on_the_floor["issued_action_count"] == 2
        assert on_the_floor["training_status"] == "CERTIFIED"

        second_coaching = validate_success(
            api.create_accountability_action(
                la1,
                factories.accountability_action_payload("COACHING", "INSPECTION_FINDING"),
                officer_headers,
            ),
            201,
        )
        assert second_coaching["score_weight"] == 5
        below_the_floor = build.read_associate(la1)
        assert_pct(below_the_floor["accountability_score"], 75.00)
        assert below_the_floor["issued_action_count"] == 3
        assert below_the_floor["training_status"] == "SUSPENDED"

        voided_coaching = validate_success(
            api.transition_accountability_action(
                second_coaching["id"],
                factories.action_transition_payload(
                    "VOIDED",
                    "Second coaching was logged against the wrong associate",
                ),
                officer_headers,
            )
        )
        assert voided_coaching["status"] == "VOIDED"
        assert (
            voided_coaching["void_reason"]
            == "Second coaching was logged against the wrong associate"
        )
        after_first_void = build.read_associate(la1)
        assert_pct(after_first_void["accountability_score"], 80.00)
        assert after_first_void["issued_action_count"] == 2
        assert after_first_void["training_status"] == "SUSPENDED"

        voided_warning = validate_success(
            api.transition_accountability_action(
                warning["id"],
                factories.action_transition_payload(
                    "VOIDED", "Warning rescinded after the grievance hearing"
                ),
                officer_headers,
            )
        )
        assert voided_warning["status"] == "VOIDED"
        after_second_void = build.read_associate(la1)
        assert_pct(after_second_void["accountability_score"], 95.00)
        assert after_second_void["issued_action_count"] == 1
        assert after_second_void["training_status"] == "SUSPENDED"

        reinstated = build.train(la1, "REMEDIAL_LABEL_101", 95)
        assert reinstated["training_status"] == "CERTIFIED"
        assert_instant_is(reinstated["certification_expires_at"], "2027-08-01T00:00:00Z")
        assert_pct(reinstated["accountability_score"], 95.00)
        assert reinstated["issued_action_count"] == 1
        assert build.read_action(first_coaching["id"])["status"] == "ISSUED"

        rows, meta = validate_paginated(
            api.list_associate_accountability_actions(la1, admin_headers)
        )
        assert meta["total_count"] == 3
        assert len([row for row in rows if row["status"] == "ISSUED"]) == 1
        assert len([row for row in rows if row["status"] == "VOIDED"]) == 2

    def test_the_refused_undo_moves_nothing_and_reinstatement_is_a_separate_forward_step(
        self, api, build, officer_headers, admin_headers
    ):
        """A void without a reason, a repeated void and a wrong module all leave the ledger alone.

        PRD 3.2: "The weight assigned to an action by its `action_type` is 5 for
        `COACHING`, 10 for `RETRAINING_ASSIGNED`, 15 for `WRITTEN_WARNING` and 25 for
        `SUSPENSION`, and that weight is stored on the action itself as `score_weight`."
        PRD 3.2: "Issuing an action against an already-`SUSPENDED` associate is refused
        with `ERR_ASSOCIATE_INVALID_STATE`."
        PRD 3.2: "A void with no `void_reason`, or an empty one, is refused with
        `ERR_VOID_REASON_REQUIRED`; attempting either transition on an action that is
        already `COMPLETED` or `VOIDED` is refused with `ERR_ACTION_INVALID_STATE`."
        PRD 3.2: "Alternatively a store manager or compliance officer voids it,
        supplying `target_status` of `VOIDED` together with a `void_reason`; voiding is
        the compensating operation for the accountability-score invariant, and after it
        the score returns to **exactly** its pre-issue value."
        PRD 3.2: "Voiding never changes `training_status`, so voiding the action that
        caused a suspension does not by itself reinstate the associate."
        PRD 3.2: "A `SUSPENDED` associate is reinstated only by completing the remedial
        module `REMEDIAL_LABEL_101` with a score of at least 80."
        PRD 3.2: "Recording any other module for a suspended associate is refused with
        `ERR_ASSOCIATE_INVALID_STATE`, and recording `REMEDIAL_LABEL_101` with a score
        below 80 is refused with `ERR_TRAINING_SCORE_TOO_LOW`."

        Design: Difficulty/compensating_invariant/accountability_score_returns_to_its_pre_issue_value_after_voids
        """
        jurisdiction_id = build.jurisdiction(
            code="US-CA", accountability_variant="OCCURRENCE_WEIGHTED"
        )
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        la1 = build.certified(
            store_id,
            ROLE_CODE_LABEL_ASSOCIATE,
            employee_number="E-LA1",
            full_name="Lena Label",
        )
        assert_pct(build.read_associate(la1)["accountability_score"], 100.00)

        suspension = validate_success(
            api.create_accountability_action(
                la1,
                factories.accountability_action_payload("SUSPENSION", "AUDIT_FAIL"),
                officer_headers,
            ),
            201,
        )
        assert suspension["score_weight"] == 25
        assert suspension["status"] == "ISSUED"
        suspended = build.read_associate(la1)
        assert_pct(suspended["accountability_score"], 75.00)
        assert suspended["issued_action_count"] == 1
        assert suspended["training_status"] == "SUSPENDED"

        validate_error(
            api.create_accountability_action(
                la1,
                factories.accountability_action_payload("COACHING", "INSPECTION_FINDING"),
                officer_headers,
            ),
            ERR_ASSOCIATE_INVALID_STATE,
            409,
        )
        validate_error(
            api.transition_accountability_action(
                suspension["id"],
                factories.action_transition_payload("VOIDED", ""),
                officer_headers,
            ),
            ERR_VOID_REASON_REQUIRED,
            422,
        )
        unmoved = build.read_associate(la1)
        assert_pct(unmoved["accountability_score"], 75.00)
        assert unmoved["issued_action_count"] == 1
        assert build.read_action(suspension["id"])["status"] == "ISSUED"

        voided = validate_success(
            api.transition_accountability_action(
                suspension["id"],
                factories.action_transition_payload(
                    "VOIDED", "Suspension was rescinded by the works council"
                ),
                officer_headers,
            )
        )
        assert voided["status"] == "VOIDED"
        restored = build.read_associate(la1)
        assert_pct(restored["accountability_score"], 100.00)
        assert restored["issued_action_count"] == 0
        assert restored["training_status"] == "SUSPENDED"

        validate_error(
            api.transition_accountability_action(
                suspension["id"],
                factories.action_transition_payload("VOIDED", "Filed twice by mistake"),
                officer_headers,
            ),
            ERR_ACTION_INVALID_STATE,
            409,
        )
        assert_pct(build.read_associate(la1)["accountability_score"], 100.00)

        validate_error(
            api.record_training_completion(
                la1, factories.training_payload("LABEL_101", 95), admin_headers
            ),
            ERR_ASSOCIATE_INVALID_STATE,
            409,
        )
        validate_error(
            api.record_training_completion(
                la1, factories.training_payload("REMEDIAL_LABEL_101", 79), admin_headers
            ),
            ERR_TRAINING_SCORE_TOO_LOW,
            422,
        )
        assert build.read_associate(la1)["training_status"] == "SUSPENDED"

        reinstated = build.train(la1, "REMEDIAL_LABEL_101", 95)
        assert reinstated["training_status"] == "CERTIFIED"
        assert_instant_is(reinstated["certification_expires_at"], "2027-08-01T00:00:00Z")
        assert_pct(reinstated["accountability_score"], 100.00)
        assert reinstated["issued_action_count"] == 0

        retraining = validate_success(
            api.create_accountability_action(
                la1,
                factories.accountability_action_payload(
                    "RETRAINING_ASSIGNED", "EXCEPTION_ROOT_CAUSE"
                ),
                officer_headers,
            ),
            201,
        )
        assert retraining["score_weight"] == 10
        after_retraining = build.read_associate(la1)
        assert_pct(after_retraining["accountability_score"], 90.00)
        assert after_retraining["issued_action_count"] == 1
        assert after_retraining["training_status"] == "CERTIFIED"

        validate_success(
            api.transition_accountability_action(
                retraining["id"],
                factories.action_transition_payload(
                    "VOIDED", "Root cause was reassigned to the receiving team"
                ),
                officer_headers,
            )
        )
        final_associate = build.read_associate(la1)
        assert_pct(final_associate["accountability_score"], 100.00)
        assert final_associate["issued_action_count"] == 0
        assert final_associate["training_status"] == "CERTIFIED"

        rows, meta = validate_paginated(
            api.list_associate_accountability_actions(la1, admin_headers, {"status": "VOIDED"})
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {suspension["id"], retraining["id"]}
        issued_rows, issued_meta = validate_paginated(
            api.list_associate_accountability_actions(la1, admin_headers, {"status": "ISSUED"})
        )
        assert issued_meta["total_count"] == 0
        assert issued_rows == []
