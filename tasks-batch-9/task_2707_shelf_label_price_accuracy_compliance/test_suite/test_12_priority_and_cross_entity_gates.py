"""Two rules broken at once, and gates that live on another entity entirely."""

from test_helpers import (
    assert_instant_is,
    assert_money_cents,
    assert_pct,
    expected_penalty_exposure_cents,
    factories,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_AUDIT_NOT_CLOSED,
    ERR_EVIDENCE_AUDIT_NOT_CLOSED,
    ERR_FILE_NOT_DISTRIBUTED,
    ERR_REFUND_BUDGET_EXCEEDED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_VERIFICATION_WINDOW_CLOSED,
)
from test_helpers.constants import (
    ROLE_CODE_LABEL_ASSOCIATE,
    ROLE_CODE_PRICE_AUDITOR,
    ROLE_CODE_STORE_MANAGER,
)

TWO_OVERCHARGES = [
    {"item_upc": "00000000000501", "shelf_price_cents": 949, "register_price_cents": 1099},
    {"item_upc": "00000000000502", "shelf_price_cents": 349, "register_price_cents": 499},
]

FOUR_LINES_ONE_OVERCHARGE = [
    {"item_upc": "00000000001101", "shelf_price_cents": 949, "register_price_cents": 1099},
    {"item_upc": "00000000001102", "shelf_price_cents": 299, "register_price_cents": 299},
    {"item_upc": "00000000001103", "shelf_price_cents": 199, "register_price_cents": 199},
    {"item_upc": "00000000001104", "shelf_price_cents": 399, "register_price_cents": 399},
]

MILK_1_GAL = {
    "item_upc": "00000000001001",
    "item_description": "Milk 1gal",
    "category_code": "DAIRY",
    "old_retail_cents": 449,
    "new_retail_cents": 399,
    "net_content_qty": 1,
    "net_content_uom": "GAL",
}

BUTTER_1_LB = {
    "item_upc": "00000000001002",
    "item_description": "Butter 1lb",
    "category_code": "DAIRY",
    "old_retail_cents": 549,
    "new_retail_cents": 499,
    "net_content_qty": 1,
    "net_content_uom": "LB",
}

VERIFY_LINE = {
    "item_upc": "00000000000601",
    "item_description": "Milk 1gal",
    "category_code": "DAIRY",
    "old_retail_cents": 449,
    "new_retail_cents": 399,
    "net_content_qty": 1,
    "net_content_uom": "GAL",
}


class TestRefundStateBeatsRefundBudget:
    def test_the_reopened_audit_answers_before_the_exhausted_budget_does(
        self, api, build, desk_headers
    ):
        """One claim over budget against a reopened audit reports the state, and each arm isolates one rule.

        PRD 2.9: "When a single request would fail several checks, the response
        must report the failure the ladder reaches first."
        PRD 2.9: "A refund claim may only be created against a scan line whose
        owning audit is `CLOSED`."
        PRD 2.9: "The store's outstanding refund liability plus this claim's
        computed amount may not exceed the jurisdiction's per-audit refund
        budget."
        PRD 3.8: "Under `REFUND_DIFFERENCE_PLUS_FIXED` the gross amount is the
        variance plus the jurisdiction's `refund_fixed_bonus_cents` goodwill
        payment."
        PRD 3.8: "And the store's outstanding refund liability plus this claim's
        computed amount may not exceed the jurisdiction's
        `refund_budget_per_audit_cents`, refusing otherwise with
        `ERR_REFUND_BUDGET_EXCEEDED`."
        PRD 3.5: "On success the verdict is withdrawn: `outcome` returns to
        `PENDING`, and `error_rate_pct`, `rate_variant_applied`,
        `gross_error_rate_pct`, `net_overcharge_rate_pct` and `closed_at` all
        return to null."
        PRD 2.7: "`refund_liability_outstanding_cents` is the sum of the claimed
        amounts of this store's refund claims whose status is `PENDING` or
        `APPROVED`."

        Design: Difficulty/priority_pair_validation_conflict/refund_claim_state_priority_42_beats_fiscal_budget_priority_72
        """
        jurisdiction_id = build.jurisdiction(
            code="US-CA",
            overcharge_refund_policy="REFUND_DIFFERENCE_PLUS_FIXED",
            refund_fixed_bonus_cents=500,
            refund_cap_cents=5000,
            refund_budget_per_audit_cents=700,
            scanner_error_rate_threshold_pct=25.0,
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
        auditor_headers = build.auditor(auditor_id)

        built = build.closed_audit(
            store_id,
            aisle_id,
            auditor_id,
            TWO_OVERCHARGES,
            scan_window_start="2026-08-01T08:00:00Z",
            scan_window_end="2026-08-01T10:00:00Z",
        )
        audit_id = built["audit_id"]
        line_a, line_b = built["scan_line_ids"]

        claim_a = build.refund_claim(line_a, "CUST-A", built["version"])
        assert_money_cents(claim_a["claimed_amount_cents"], 650)
        assert claim_a["policy_applied"] == "REFUND_DIFFERENCE_PLUS_FIXED"
        assert claim_a["status"] == "PENDING"
        assert_money_cents(
            build.read_store(store_id)["refund_liability_outstanding_cents"], 650
        )

        reopened = build.reopen_audit(audit_id, "Register export was incomplete")
        assert reopened["status"] == "REOPENED"
        assert reopened["outcome"] == "PENDING"
        assert reopened["closed_at"] is None

        validate_error(
            api.create_refund_claim(
                factories.refund_claim_payload(line_b, "CUST-B", reopened["version"]),
                desk_headers,
            ),
            ERR_AUDIT_NOT_CLOSED,
            409,
        )

        rows, meta = validate_paginated(
            api.list_refund_claims(build.desk, {"scan_line_id": line_b})
        )
        assert meta["total_count"] == 0
        assert rows == []
        assert_money_cents(
            build.read_store(store_id)["refund_liability_outstanding_cents"], 650
        )

        reclosed = build.close_audit(audit_id, auditor_headers)
        assert reclosed["status"] == "CLOSED"
        assert_pct(reclosed["error_rate_pct"], 100.00)
        validate_error(
            api.create_refund_claim(
                factories.refund_claim_payload(line_b, "CUST-B", reclosed["version"]),
                desk_headers,
            ),
            ERR_REFUND_BUDGET_EXCEEDED,
            422,
        )

        reopened_again = build.reopen_audit(audit_id, "Register export was incomplete")
        assert reopened_again["reopen_count"] == 2
        amended = build.amend_jurisdiction(
            jurisdiction_id, {"refund_budget_per_audit_cents": 5000}
        )
        assert_money_cents(amended["refund_budget_per_audit_cents"], 5000)
        validate_error(
            api.create_refund_claim(
                factories.refund_claim_payload(
                    line_b, "CUST-B", reopened_again["version"]
                ),
                desk_headers,
            ),
            ERR_AUDIT_NOT_CLOSED,
            409,
        )

        finally_closed = build.close_audit(audit_id, auditor_headers)
        claim_b = build.refund_claim(line_b, "CUST-B", finally_closed["version"])
        assert_money_cents(claim_b["claimed_amount_cents"], 650)
        assert claim_b["status"] == "PENDING"
        assert claim_b["store_id"] == store_id
        assert_money_cents(
            build.read_store(store_id)["refund_liability_outstanding_cents"], 1300
        )

    def test_denying_the_first_claim_frees_the_ledger_but_never_reorders_the_ladder(
        self, api, build, desk_headers
    ):
        """The budget can be compensated away and re-exhausted; the state gate keeps winning whenever it holds.

        PRD 2.9: "When a single request would fail several checks, the response
        must report the failure the ladder reaches first."
        PRD 2.9: "A refund claim may only be created against a scan line whose
        owning audit is `CLOSED`."
        PRD 2.9: "The ladder for this domain runs: authentication, then
        authorization, then schema, then existence, then the target's own state,
        then cross-entity state, then version pinning, then regulatory and
        segregation-of-duties rules, then temporal rules, then constraint and
        uniqueness rules, and finally fiscal rules — budgets, caps and quotas
        are always evaluated last, so a request that is both over budget and
        malformed reports the malformed body."
        PRD 3.8: "A store manager denies a claim, moving it to `DENIED` from
        either `PENDING` or `APPROVED` — the two source states behave
        identically — storing the `denial_reason` and recomputing the store's
        `refund_liability_outstanding_cents`, from which this claim's amount now
        departs."
        PRD 3.8: "Only one claim may exist per scan-line-and-customer pair, a
        repeat yielding `ERR_DUPLICATE_RESOURCE`; a second, different customer
        may legitimately claim against the same observation."
        PRD 3.5: "The audit then walks `CLOSED → REOPENED → SCANNING → CLOSED`,
        and that cycle may repeat."

        Design: Difficulty/priority_pair_validation_conflict/refund_claim_state_priority_42_beats_fiscal_budget_priority_72
        """
        jurisdiction_id = build.jurisdiction(
            code="US-CA",
            overcharge_refund_policy="REFUND_DIFFERENCE_PLUS_FIXED",
            refund_fixed_bonus_cents=500,
            refund_cap_cents=5000,
            refund_budget_per_audit_cents=700,
            scanner_error_rate_threshold_pct=25.0,
        )
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        aisle_id = build.aisle(store_id, aisle_code="A01", category_code="DAIRY")
        manager_id = build.certified(
            store_id,
            ROLE_CODE_STORE_MANAGER,
            employee_number="E-SM1",
            full_name="Sam Manager",
        )
        auditor_id = build.certified(
            store_id,
            ROLE_CODE_PRICE_AUDITOR,
            module_code="AUDIT_101",
            employee_number="E-PA1",
            full_name="Pat Auditor",
        )
        auditor_headers = build.auditor(auditor_id)
        manager_headers = build.manager(manager_id)

        built = build.closed_audit(
            store_id,
            aisle_id,
            auditor_id,
            TWO_OVERCHARGES,
            scan_window_start="2026-08-01T08:00:00Z",
            scan_window_end="2026-08-01T10:00:00Z",
        )
        audit_id = built["audit_id"]
        line_a, line_b = built["scan_line_ids"]

        claim_a = build.refund_claim(line_a, "CUST-A", built["version"])
        assert_money_cents(claim_a["claimed_amount_cents"], 650)

        build.reopen_audit(audit_id, "Register export was incomplete")
        validate_error(
            api.create_refund_claim(
                factories.refund_claim_payload(
                    line_b, "CUST-B", build.audit_version(audit_id)
                ),
                desk_headers,
            ),
            ERR_AUDIT_NOT_CLOSED,
            409,
        )

        denied = build.settle_claim(
            claim_a["id"],
            "DENIED",
            manager_headers,
            denial_reason="Customer could not produce the receipt",
        )
        assert denied["status"] == "DENIED"
        assert denied["denial_reason"] == "Customer could not produce the receipt"
        assert_money_cents(
            build.read_store(store_id)["refund_liability_outstanding_cents"], 0
        )

        validate_error(
            api.create_refund_claim(
                factories.refund_claim_payload(
                    line_b, "CUST-B", build.audit_version(audit_id)
                ),
                desk_headers,
            ),
            ERR_AUDIT_NOT_CLOSED,
            409,
        )

        build.close_audit(audit_id, auditor_headers)
        claim_b = build.refund_claim(line_b, "CUST-B", build.audit_version(audit_id))
        assert_money_cents(claim_b["claimed_amount_cents"], 650)
        assert claim_b["status"] == "PENDING"
        assert_money_cents(
            build.read_store(store_id)["refund_liability_outstanding_cents"], 650
        )

        validate_error(
            api.create_refund_claim(
                factories.refund_claim_payload(
                    line_b, "CUST-C", build.audit_version(audit_id)
                ),
                desk_headers,
            ),
            ERR_REFUND_BUDGET_EXCEEDED,
            422,
        )

        build.reopen_audit(audit_id, "Register export was incomplete")
        validate_error(
            api.create_refund_claim(
                factories.refund_claim_payload(
                    line_b, "CUST-C", build.audit_version(audit_id)
                ),
                desk_headers,
            ),
            ERR_AUDIT_NOT_CLOSED,
            409,
        )

        rows, meta = validate_paginated(
            api.list_refund_claims(build.desk, {"scan_line_id": line_b})
        )
        assert meta["total_count"] == 1
        assert [row["customer_ref"] for row in rows] == ["CUST-B"]
        assert_money_cents(
            build.read_store(store_id)["refund_liability_outstanding_cents"], 650
        )


class TestSelfVerificationBeatsTheLapsedGrace:
    def test_the_self_verifier_hears_about_duties_not_about_the_window(self, api, build):
        """Two 422 rules break at once, so only the priority number can decide which one answers.

        PRD 2.9: "When a single request would fail several checks, the response
        must report the failure the ladder reaches first."
        PRD 2.9: "The verifying associate named by `X-User-ID` must differ from
        the label task's `placed_by_associate_id`."
        PRD 2.9: "Placement verification must happen within 48 hours of the label
        task's `placed_at`."
        PRD 3.4: "Both outcomes require that the verifying `X-User-ID` differs
        from the task's `placed_by_associate_id`, refusing self-verification with
        `ERR_SEGREGATION_OF_DUTIES`."
        PRD 3.4: "And verification must happen within 48 hours of `placed_at`; a
        later attempt is refused with `ERR_VERIFICATION_WINDOW_CLOSED`."
        PRD 3.2: "A result of at least 80 taken while the associate is
        `UNTRAINED` or `IN_TRAINING` moves them to `CERTIFIED` and stamps
        `certification_expires_at` at the current instant plus 365 days."
        PRD 3.4: "It stamps `verified_by_associate_id` from `X-User-ID` and
        `verified_at` from the current instant, and stores the observed shelf
        price as the verifier's reading."

        Design: Difficulty/priority_pair_validation_conflict/verify_placement_safety_priority_50_beats_temporal_priority_59
        """
        jurisdiction_id = build.jurisdiction(code="US-CA", grace_period_hours=48)
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        aisle_id = build.aisle(store_id, aisle_code="A01", category_code="DAIRY")
        manager_id = build.certified(
            store_id,
            ROLE_CODE_STORE_MANAGER,
            employee_number="E-SM1",
            full_name="Sam Manager",
        )
        auditor_id = build.certified(
            store_id,
            ROLE_CODE_PRICE_AUDITOR,
            module_code="AUDIT_101",
            employee_number="E-PA1",
            full_name="Pat Auditor",
        )
        manager_headers = build.manager(manager_id)
        auditor_headers = build.auditor(auditor_id)

        manager_record = build.read_associate(manager_id)
        assert manager_record["training_status"] == "CERTIFIED"
        assert_instant_is(
            manager_record["certification_expires_at"], "2027-08-01T00:00:00Z"
        )

        built = build.distributed_file(
            jurisdiction_id, [store_id], [VERIFY_LINE], file_number="PCF-1001"
        )
        placed = build.placed_task(
            built["file_id"],
            store_id,
            built["line_ids"][0],
            aisle_id,
            manager_id,
            399,
            placer_headers=manager_headers,
            scheduled_start_at="2026-08-03T09:00:00Z",
            scheduled_end_at="2026-08-03T10:00:00Z",
        )
        task_id = placed["task_id"]
        assert placed["task"]["placed_by_associate_id"] == manager_id
        assert_instant_is(placed["task"]["placed_at"], "2026-08-01T00:00:00Z")

        build.set_clock("2026-08-03T01:00:00Z")
        validate_error(
            api.verify_label_task_placement(
                task_id, factories.verify_payload("VERIFIED"), manager_headers
            ),
            ERR_SEGREGATION_OF_DUTIES,
            422,
        )
        untouched = build.read_task(task_id)
        assert untouched["placement_status"] == "PLACED"
        assert untouched["verified_by_associate_id"] is None
        assert untouched["verified_at"] is None
        assert untouched["rejection_count"] == 0

        validate_error(
            api.verify_label_task_placement(
                task_id, factories.verify_payload("VERIFIED"), auditor_headers
            ),
            ERR_VERIFICATION_WINDOW_CLOSED,
            422,
        )

        build.set_clock("2026-08-01T01:00:00Z")
        validate_error(
            api.verify_label_task_placement(
                task_id, factories.verify_payload("VERIFIED"), manager_headers
            ),
            ERR_SEGREGATION_OF_DUTIES,
            422,
        )

        verified = build.verify_task(task_id, auditor_headers)
        assert verified["placement_status"] == "VERIFIED"
        assert verified["verified_by_associate_id"] == auditor_id
        assert_instant_is(verified["verified_at"], "2026-08-01T01:00:00Z")
        assert verified["observed_shelf_price_cents"] == 399
        assert build.read_line(built["line_ids"][0])["line_status"] == "VERIFIED"

    def test_the_pair_holds_on_the_rejection_path_and_a_re_placement_restarts_the_window(
        self, api, build
    ):
        """The window is measured from the current placed_at, but self-verification is refused at any clock.

        PRD 2.9: "When a single request would fail several checks, the response
        must report the failure the ladder reaches first."
        PRD 2.9: "The verifying associate named by `X-User-ID` must differ from
        the label task's `placed_by_associate_id`."
        PRD 2.9: "Placement verification must happen within 48 hours of the label
        task's `placed_at`."
        PRD 3.4: "Both outcomes require that the verifying `X-User-ID` differs
        from the task's `placed_by_associate_id`, refusing self-verification with
        `ERR_SEGREGATION_OF_DUTIES`."
        PRD 3.4: "It increments `rejection_count` by one, pushes the print axis
        from `PRINTED` back to `REPRINT_REQUIRED`, and pushes the underlying line
        `LABELED → FAILED`."
        PRD 3.4: "On success, `placed_by_associate_id` is stamped from
        `X-User-ID` and `placed_at` from the current instant, the store's label
        backlog is recomputed and then its posture recomputed, and when the
        underlying line sits in `FAILED` it moves `FAILED → LABELED`."
        PRD 2.4: "The clock's startup default is exactly `2026-08-01T00:00:00Z`;
        before any operator has advanced it, every deadline comparison,
        promotional window test, certification expiry check, verification grace
        period and thirty-day posture window reads that instant."

        Design: Difficulty/priority_pair_validation_conflict/verify_placement_safety_priority_50_beats_temporal_priority_59
        """
        jurisdiction_id = build.jurisdiction(code="US-CA", grace_period_hours=48)
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        aisle_id = build.aisle(store_id, aisle_code="A01", category_code="DAIRY")
        manager_id = build.certified(
            store_id,
            ROLE_CODE_STORE_MANAGER,
            employee_number="E-SM1",
            full_name="Sam Manager",
        )
        auditor_id = build.certified(
            store_id,
            ROLE_CODE_PRICE_AUDITOR,
            module_code="AUDIT_101",
            employee_number="E-PA1",
            full_name="Pat Auditor",
        )
        manager_headers = build.manager(manager_id)
        auditor_headers = build.auditor(auditor_id)

        built = build.distributed_file(
            jurisdiction_id, [store_id], [VERIFY_LINE], file_number="PCF-1001"
        )
        line_id = built["line_ids"][0]
        placed = build.placed_task(
            built["file_id"],
            store_id,
            line_id,
            aisle_id,
            manager_id,
            399,
            placer_headers=manager_headers,
            scheduled_start_at="2026-08-03T09:00:00Z",
            scheduled_end_at="2026-08-03T10:00:00Z",
        )
        task_id = placed["task_id"]
        assert_instant_is(placed["task"]["placed_at"], "2026-08-01T00:00:00Z")

        build.set_clock("2026-08-03T02:00:00Z")
        validate_error(
            api.verify_label_task_placement(
                task_id, factories.verify_payload("REJECTED"), manager_headers
            ),
            ERR_SEGREGATION_OF_DUTIES,
            422,
        )
        validate_error(
            api.verify_label_task_placement(
                task_id,
                factories.verify_payload("REJECTED", "Tag shows the old retail"),
                auditor_headers,
            ),
            ERR_VERIFICATION_WINDOW_CLOSED,
            422,
        )
        still_placed = build.read_task(task_id)
        assert still_placed["placement_status"] == "PLACED"
        assert still_placed["print_status"] == "PRINTED"
        assert still_placed["rejection_count"] == 0

        build.set_clock("2026-08-01T01:00:00Z")
        validate_error(
            api.verify_label_task_placement(
                task_id, factories.verify_payload("REJECTED"), manager_headers
            ),
            ERR_SEGREGATION_OF_DUTIES,
            422,
        )
        rejected = build.verify_task(
            task_id,
            auditor_headers,
            outcome="REJECTED",
            rejection_reason="Tag shows the old retail",
        )
        assert rejected["placement_status"] == "REJECTED"
        assert rejected["print_status"] == "REPRINT_REQUIRED"
        assert rejected["rejection_count"] == 1
        assert build.read_line(line_id)["line_status"] == "FAILED"

        build.set_clock("2026-08-01T02:00:00Z")
        build.print_task(task_id, manager_headers)
        replaced = build.place_task(task_id, 399, manager_headers)
        assert replaced["placement_status"] == "PLACED"
        assert replaced["placed_by_associate_id"] == manager_id
        assert_instant_is(replaced["placed_at"], "2026-08-01T02:00:00Z")
        assert build.read_line(line_id)["line_status"] == "LABELED"

        build.set_clock("2026-08-03T01:30:00Z")
        validate_error(
            api.verify_label_task_placement(
                task_id, factories.verify_payload("VERIFIED"), manager_headers
            ),
            ERR_SEGREGATION_OF_DUTIES,
            422,
        )
        verified = build.verify_task(task_id, auditor_headers)
        assert verified["placement_status"] == "VERIFIED"
        assert verified["verified_by_associate_id"] == auditor_id
        assert_instant_is(verified["verified_at"], "2026-08-03T01:30:00Z")
        assert verified["rejection_count"] == 1
        assert build.read_line(line_id)["line_status"] == "VERIFIED"
        completed = build.read_file(built["file_id"])
        assert completed["status"] == "EXECUTED"
        assert completed["verified_line_count"] == 1


class TestPrintGatedByTheOwningFile:
    def test_the_same_print_call_flips_to_a_refusal_when_the_ancestor_file_is_superseded(
        self, api, build
    ):
        """Nothing about the task changes across the two arms; only the file two hops above it moves.

        PRD 2.9: "Label printing requires the owning price change file to be
        `DISTRIBUTED` or `PARTIALLY_EXECUTED`; a `DRAFT`, `EXECUTED` or
        `SUPERSEDED` file blocks the print."
        PRD 3.4: "Printing requires the owning batch to be `DISTRIBUTED` or
        `PARTIALLY_EXECUTED`, refusing a draft, executed or superseded batch with
        `ERR_FILE_NOT_DISTRIBUTED`; it requires the store not to be `FROZEN`,
        refusing with `ERR_STORE_POSTURE_BLOCKED`; and it requires that the task's
        assigned associate is not `SUSPENDED`, refusing with
        `ERR_LABEL_TASK_INVALID_STATE`."
        PRD 3.3: "Creating the store-level execution task for a line moves it
        `PENDING → TASKED`, and that same event may auto-advance its owning batch
        `DISTRIBUTED → PARTIALLY_EXECUTED` — the batch itself changes nothing but
        its status, `updated_at` and `version` on that hop."
        PRD 3.3: "Every line of the batch whose status is not `VERIFIED` — that
        is, every line still in `PENDING`, `TASKED`, `LABELED` or `FAILED` —
        transitions to `WITHDRAWN`, and a withdrawn line permanently leaves every
        store's label backlog."
        PRD 3.3: "For each withdrawn line, every label task on it whose placement
        axis is not `VERIFIED` has its print axis forced to `REPRINT_REQUIRED`
        with its `printed_label_serial` cleared, because the tag in the printer's
        tray now shows a price nobody is allowed to charge."
        PRD 3.4: "A label associate or store manager prints the tag, moving the
        print axis to `PRINTED` from either `NOT_PRINTED` or `REPRINT_REQUIRED`."
        PRD 2.7: "`label_backlog_count` is the number of this store's label tasks
        whose placement axis is `UNPLACED` or `REJECTED` **and** whose underlying
        price change line is not `WITHDRAWN`."

        Design: Difficulty/cross_entity_state_dependency/label_print_blocked_by_owning_file_leaving_the_distributed_states
        """
        jurisdiction_id = build.jurisdiction(code="US-CA", grace_period_hours=48)
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        aisle_id = build.aisle(store_id, aisle_code="A01", category_code="DAIRY")
        associate_id = build.certified(
            store_id,
            ROLE_CODE_LABEL_ASSOCIATE,
            employee_number="E-LA1",
            full_name="Lena Label",
        )
        associate_headers = build.associate_headers(associate_id)

        built = build.distributed_file(
            jurisdiction_id,
            [store_id],
            [MILK_1_GAL, BUTTER_1_LB],
            file_number="PCF-1001",
        )
        file_id = built["file_id"]
        line_1, line_2 = built["line_ids"]
        assert built["file"]["status"] == "DISTRIBUTED"

        replacement = build.price_change_file(
            jurisdiction_id,
            [store_id],
            effective_date="2026-08-04T00:00:00Z",
            file_number="PCF-1002",
        )
        assert replacement["status"] == "DRAFT"

        task_1 = build.label_task(
            file_id,
            store_id,
            line_1,
            aisle_id,
            associate_id,
            "2026-08-03T09:00:00Z",
            "2026-08-03T10:00:00Z",
            built["version"],
        )
        assert build.read_file(file_id)["status"] == "PARTIALLY_EXECUTED"
        task_2 = build.label_task(
            file_id,
            store_id,
            line_2,
            aisle_id,
            associate_id,
            "2026-08-03T11:00:00Z",
            "2026-08-03T12:00:00Z",
            build.file_version(file_id),
        )

        printed = build.print_task(task_1["id"], associate_headers)
        assert printed["print_status"] == "PRINTED"
        assert printed["printed_label_serial"].startswith("LBL-")
        assert build.read_line(line_1)["line_status"] == "LABELED"
        before_supersede = build.read_file(file_id)
        assert before_supersede["status"] == "PARTIALLY_EXECUTED"

        superseded = validate_success(
            api.supersede_price_change_file(
                file_id, factories.supersede_payload(replacement["id"]), build.admin
            )
        )
        assert superseded["status"] == "SUPERSEDED"
        assert superseded["superseded_by_file_id"] == replacement["id"]
        assert superseded["version"] == before_supersede["version"] + 1
        assert build.read_file(replacement["id"])["status"] == "DRAFT"
        assert build.read_line(line_1)["line_status"] == "WITHDRAWN"
        assert build.read_line(line_2)["line_status"] == "WITHDRAWN"

        reset_1 = build.read_task(task_1["id"])
        assert reset_1["print_status"] == "REPRINT_REQUIRED"
        assert reset_1["printed_label_serial"] is None
        reset_2 = build.read_task(task_2["id"])
        assert reset_2["print_status"] == "REPRINT_REQUIRED"
        assert reset_2["placement_status"] == "UNPLACED"

        validate_error(
            api.print_label_task(task_2["id"], associate_headers),
            ERR_FILE_NOT_DISTRIBUTED,
            409,
        )
        validate_error(
            api.print_label_task(task_1["id"], associate_headers),
            ERR_FILE_NOT_DISTRIBUTED,
            409,
        )
        assert build.read_task(task_2["id"])["print_status"] == "REPRINT_REQUIRED"

        store = build.read_store(store_id)
        assert store["label_backlog_count"] == 0
        assert store["compliance_posture"] == "OPEN"

    def test_completing_the_file_in_one_store_blocks_the_untouched_print_in_the_other(
        self, api, build
    ):
        """The third blocked ancestor state is reached by completion, and the blocked task never moved.

        PRD 2.9: "Label printing requires the owning price change file to be
        `DISTRIBUTED` or `PARTIALLY_EXECUTED`; a `DRAFT`, `EXECUTED` or
        `SUPERSEDED` file blocks the print."
        PRD 3.4: "Printing requires the owning batch to be `DISTRIBUTED` or
        `PARTIALLY_EXECUTED`, refusing a draft, executed or superseded batch with
        `ERR_FILE_NOT_DISTRIBUTED`; it requires the store not to be `FROZEN`,
        refusing with `ERR_STORE_POSTURE_BLOCKED`; and it requires that the task's
        assigned associate is not `SUSPENDED`, refusing with
        `ERR_LABEL_TASK_INVALID_STATE`."
        PRD 3.3: "A batch in `PARTIALLY_EXECUTED` advances `PARTIALLY_EXECUTED →
        EXECUTED` the moment a line's move into `VERIFIED` makes the verified-line
        count equal the line count, provided the line count is at least 1."
        PRD 3.3: "On completion, every store named in the batch's
        `scope_store_ids` has its `executed_file_count` raised by one, then its
        label backlog recomputed, then its posture recomputed, in that order."
        PRD 3.4: "The aisle must belong to the named store or the request fails
        with `ERR_AISLE_STORE_MISMATCH`; the assigned associate must belong to the
        named store or it fails with `ERR_ASSOCIATE_STORE_MISMATCH`; the store
        must appear in the batch's scope and share the batch's jurisdiction or it
        fails with `ERR_STORE_OUT_OF_FILE_SCOPE`; and only one task may exist for
        any given line-and-store pair, a second attempt yielding
        `ERR_DUPLICATE_RESOURCE`."
        PRD 2.7: "`label_backlog_count` is the number of this store's label tasks
        whose placement axis is `UNPLACED` or `REJECTED` **and** whose underlying
        price change line is not `WITHDRAWN`."

        Design: Difficulty/cross_entity_state_dependency/label_print_blocked_by_owning_file_leaving_the_distributed_states
        """
        jurisdiction_id = build.jurisdiction(code="US-CA", grace_period_hours=48)
        store_a = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        store_b = build.store(jurisdiction_id, store_number="S002", name="Elm Road")
        aisle_a = build.aisle(store_a, aisle_code="A01", category_code="DAIRY")
        aisle_b = build.aisle(store_b, aisle_code="B01", category_code="DAIRY")
        placer_a = build.certified(
            store_a,
            ROLE_CODE_LABEL_ASSOCIATE,
            employee_number="E-LA1",
            full_name="Lena Label",
        )
        placer_b = build.certified(
            store_b,
            ROLE_CODE_LABEL_ASSOCIATE,
            employee_number="E-LA2",
            full_name="Leo Label",
        )
        auditor_id = build.certified(
            store_a,
            ROLE_CODE_PRICE_AUDITOR,
            module_code="AUDIT_101",
            employee_number="E-PA1",
            full_name="Pat Auditor",
        )
        headers_a = build.associate_headers(placer_a)
        headers_b = build.associate_headers(placer_b)
        auditor_headers = build.auditor(auditor_id)

        built = build.distributed_file(
            jurisdiction_id, [store_a, store_b], [MILK_1_GAL], file_number="PCF-1001"
        )
        file_id = built["file_id"]
        line_id = built["line_ids"][0]

        task_a = build.label_task(
            file_id,
            store_a,
            line_id,
            aisle_a,
            placer_a,
            "2026-08-03T09:00:00Z",
            "2026-08-03T10:00:00Z",
            built["version"],
        )
        task_b = build.label_task(
            file_id,
            store_b,
            line_id,
            aisle_b,
            placer_b,
            "2026-08-03T09:00:00Z",
            "2026-08-03T10:00:00Z",
            build.file_version(file_id),
        )
        assert build.read_file(file_id)["status"] == "PARTIALLY_EXECUTED"

        printed = build.print_task(task_a["id"], headers_a)
        assert printed["print_status"] == "PRINTED"
        build.place_task(task_a["id"], 399, headers_a)
        verified = build.verify_task(task_a["id"], auditor_headers)
        assert verified["placement_status"] == "VERIFIED"

        completed = build.read_file(file_id)
        assert completed["status"] == "EXECUTED"
        assert completed["line_count"] == 1
        assert completed["verified_line_count"] == 1
        assert build.read_line(line_id)["line_status"] == "VERIFIED"

        summary_a = build.read_store(store_a)
        assert summary_a["executed_file_count"] == 1
        assert summary_a["label_backlog_count"] == 0
        assert summary_a["compliance_posture"] == "OPEN"
        summary_b = build.read_store(store_b)
        assert summary_b["executed_file_count"] == 1
        assert summary_b["label_backlog_count"] == 1
        assert summary_b["compliance_posture"] == "OPEN"

        pending = build.read_task(task_b["id"])
        assert pending["print_status"] == "NOT_PRINTED"
        assert pending["placement_status"] == "UNPLACED"
        assert build.read_associate(placer_b)["training_status"] == "CERTIFIED"

        validate_error(
            api.print_label_task(task_b["id"], headers_b),
            ERR_FILE_NOT_DISTRIBUTED,
            409,
        )
        untouched = build.read_task(task_b["id"])
        assert untouched["print_status"] == "NOT_PRINTED"
        assert untouched["printed_label_serial"] is None


class TestIssueFindingsGatedByTheEvidenceAudit:
    def test_a_reopen_invalidates_the_evidence_and_re_closing_restores_the_same_call(
        self, api, build, officer_headers
    ):
        """The inspection never leaves SCHEDULED; the peer it cites decides whether the call is legal.

        PRD 2.9: "Issuing inspection findings requires the inspection's evidence
        audit to be `CLOSED`."
        PRD 3.7: "An empty `findings` array is refused with `ERR_FINDINGS_EMPTY`;
        issuing findings against an inspection that has left `SCHEDULED` is
        refused with `ERR_INSPECTION_INVALID_STATE`; and the evidence audit must
        be `CLOSED`, refusing otherwise with `ERR_EVIDENCE_AUDIT_NOT_CLOSED`."
        PRD 3.5: "Reopening is refused with `ERR_AUDIT_INVALID_STATE` when the
        audit is not `CLOSED`, and also when any regulatory inspection using this
        audit as its evidence of record has already reached `CLOSED` — evidence
        that has been adjudicated cannot be retroactively rewritten."
        PRD 3.7: "A new inspection starts `SCHEDULED` with `finding_count`,
        `penalty_exposure_cents`, `refund_liability_cents`, `refund_credit_cents`
        and `response_round` all 0, and with `assessed_penalty_cents`,
        `remediation_summary` and `closed_at` all null."
        PRD 3.7: "An **audit aggravator** of 25 percentage points is added when
        the referenced evidence audit's outcome is `FAIL`, and 0 percentage points
        otherwise."
        PRD 3.7: "Issuing findings computes every non-waived finding's penalty
        component, computes the inspection's exposure, re-derives `finding_count`,
        and advances the inspection's `version` by one."
        PRD 3.7: "Because the findings have no creation response of their own, the
        per-inspection finding list — filterable by `status` and `severity` — is
        the only channel through which a client discovers them."

        Design: Difficulty/cross_entity_state_dependency/issue_findings_blocked_by_evidence_audit_leaving_closed
        """
        jurisdiction_id = build.jurisdiction(
            code="US-CA",
            scanner_error_rate_threshold_pct=25.0,
            penalty_per_violation_cents=5000,
            penalty_max_cents=2000000,
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
        auditor_headers = build.auditor(auditor_id)

        built = build.closed_audit(
            store_id,
            aisle_id,
            auditor_id,
            FOUR_LINES_ONE_OVERCHARGE,
            audit_type="REGULATORY",
            scan_window_start="2026-08-01T08:00:00Z",
            scan_window_end="2026-08-01T10:00:00Z",
        )
        audit_id = built["audit_id"]
        assert_pct(built["audit"]["error_rate_pct"], 25.00)
        assert built["audit"]["outcome"] == "FAIL"

        inspection = build.inspection(
            store_id,
            audit_id,
            inspector_ref="INS-77",
            inspection_date="2026-08-01T00:00:00Z",
        )
        inspection_id = inspection["id"]
        assert inspection["status"] == "SCHEDULED"
        assert inspection["finding_count"] == 0
        assert_money_cents(inspection["penalty_exposure_cents"], 0)

        reopened = build.reopen_audit(
            audit_id, "Register export re-pulled for the regulator"
        )
        assert reopened["status"] == "REOPENED"
        assert reopened["outcome"] == "PENDING"
        assert reopened["reopen_count"] == 1

        held = build.read_inspection(inspection_id)
        assert held["status"] == "SCHEDULED"
        assert held["finding_count"] == 0
        assert_money_cents(held["penalty_exposure_cents"], 0)

        findings_body = factories.issue_findings_payload(
            [factories.finding_input("SCANNER_ERROR_RATE", "MAJOR", 4)]
        )
        validate_error(
            api.issue_inspection_findings(inspection_id, findings_body, officer_headers),
            ERR_EVIDENCE_AUDIT_NOT_CLOSED,
            409,
        )
        rows, meta = validate_paginated(
            api.list_inspection_findings(inspection_id, officer_headers)
        )
        assert meta["total_count"] == 0
        assert rows == []

        reclosed = build.close_audit(audit_id, auditor_headers)
        assert reclosed["status"] == "CLOSED"
        assert_pct(reclosed["error_rate_pct"], 25.00)
        assert reclosed["outcome"] == "FAIL"

        version_before = build.inspection_version(inspection_id)
        issued = validate_success(
            api.issue_inspection_findings(inspection_id, findings_body, officer_headers)
        )
        assert issued["status"] == "FINDINGS_ISSUED"
        assert issued["finding_count"] == 1
        assert issued["version"] == version_before + 1
        assert_money_cents(
            issued["penalty_exposure_cents"],
            expected_penalty_exposure_cents(
                [{"severity": "MAJOR", "affected_item_count": 4}], 5000, 2000000, True
            ),
        )
        assert_money_cents(issued["penalty_exposure_cents"], 75000)

        rows, meta = validate_paginated(
            api.list_inspection_findings(inspection_id, officer_headers)
        )
        assert meta["total_count"] == 1
        assert rows[0]["status"] == "OPEN"
        assert rows[0]["finding_code"] == "SCANNER_ERROR_RATE"
        assert_money_cents(rows[0]["penalty_component_cents"], 60000)

        store = build.read_store(store_id)
        assert store["failed_audit_count_30d"] == 1
        assert store["escalated_finding_count"] == 0
        assert store["compliance_posture"] == "RESTRICTED"

    def test_the_gate_wants_exactly_closed_and_the_restored_verdict_changes_the_price(
        self, api, build, officer_headers
    ):
        """SCANNING is refused just as REOPENED is, and re-closing to PASS drops the aggravator from the same body.

        PRD 2.9: "Issuing inspection findings requires the inspection's evidence
        audit to be `CLOSED`."
        PRD 3.7: "An empty `findings` array is refused with `ERR_FINDINGS_EMPTY`;
        issuing findings against an inspection that has left `SCHEDULED` is
        refused with `ERR_INSPECTION_INVALID_STATE`; and the evidence audit must
        be `CLOSED`, refusing otherwise with `ERR_EVIDENCE_AUDIT_NOT_CLOSED`."
        PRD 3.5: "The audit then walks `CLOSED → REOPENED → SCANNING → CLOSED`,
        and that cycle may repeat."
        PRD 3.5: "The **gross mismatch** rate, stored as `gross_error_rate_pct`,
        is the overcharge count plus the undercharge count, divided by the sample
        size, multiplied by 100, and rounded half up to two decimal places."
        PRD 3.7: "An **audit aggravator** of 25 percentage points is added when
        the referenced evidence audit's outcome is `FAIL`, and 0 percentage points
        otherwise."
        PRD 3.7: "Each considered finding's `penalty_component_cents` is its
        severity weight — 1 for `MINOR`, 3 for `MAJOR`, 8 for `CRITICAL` —
        multiplied by the jurisdiction's `penalty_per_violation_cents`,
        multiplied by the smaller of the finding's `affected_item_count` and the
        per-finding item cap of 10."
        PRD 2.7: "`failed_audit_count_30d` is the number of this store's scanner
        audits that are `CLOSED`, carry outcome `FAIL`, and whose closing instant
        is at or after the instant thirty days before the current instant."

        Design: Difficulty/cross_entity_state_dependency/issue_findings_blocked_by_evidence_audit_leaving_closed
        """
        jurisdiction_id = build.jurisdiction(
            code="US-CA",
            scanner_error_rate_threshold_pct=25.0,
            default_rate_variant="GROSS_MISMATCH",
            penalty_per_violation_cents=5000,
            penalty_max_cents=2000000,
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
        auditor_headers = build.auditor(auditor_id)

        built = build.closed_audit(
            store_id,
            aisle_id,
            auditor_id,
            FOUR_LINES_ONE_OVERCHARGE,
            audit_type="REGULATORY",
            scan_window_start="2026-08-01T08:00:00Z",
            scan_window_end="2026-08-01T10:00:00Z",
        )
        audit_id = built["audit_id"]
        assert built["audit"]["sample_size"] == 4
        assert built["audit"]["outcome"] == "FAIL"

        inspection = build.inspection(
            store_id,
            audit_id,
            inspector_ref="INS-78",
            inspection_date="2026-08-01T00:00:00Z",
        )
        inspection_id = inspection["id"]
        findings_body = factories.issue_findings_payload(
            [factories.finding_input("SCANNER_ERROR_RATE", "MAJOR", 4)]
        )

        reopened = build.reopen_audit(
            audit_id, "Register export re-pulled for the regulator"
        )
        assert reopened["status"] == "REOPENED"
        validate_error(
            api.issue_inspection_findings(inspection_id, findings_body, officer_headers),
            ERR_EVIDENCE_AUDIT_NOT_CLOSED,
            409,
        )

        fifth = build.scan_line(audit_id, "00000000001105", 259, 259, auditor_headers)
        assert fifth["classification"] == "MATCH"
        assert build.read_audit(audit_id)["status"] == "SCANNING"
        validate_error(
            api.issue_inspection_findings(inspection_id, findings_body, officer_headers),
            ERR_EVIDENCE_AUDIT_NOT_CLOSED,
            409,
        )
        assert build.read_inspection(inspection_id)["status"] == "SCHEDULED"

        reclosed = build.close_audit(audit_id, auditor_headers)
        assert reclosed["status"] == "CLOSED"
        assert reclosed["sample_size"] == 5
        assert reclosed["overcharge_count"] == 1
        assert_pct(reclosed["gross_error_rate_pct"], 20.00)
        assert_pct(reclosed["error_rate_pct"], 20.00)
        assert reclosed["outcome"] == "PASS"

        version_before = build.inspection_version(inspection_id)
        issued = validate_success(
            api.issue_inspection_findings(inspection_id, findings_body, officer_headers)
        )
        assert issued["status"] == "FINDINGS_ISSUED"
        assert issued["finding_count"] == 1
        assert issued["version"] == version_before + 1
        assert_money_cents(
            issued["penalty_exposure_cents"],
            expected_penalty_exposure_cents(
                [{"severity": "MAJOR", "affected_item_count": 4}], 5000, 2000000, False
            ),
        )
        assert_money_cents(issued["penalty_exposure_cents"], 60000)
        assert issued["penalty_exposure_cents"] != 75000

        rows, meta = validate_paginated(
            api.list_inspection_findings(inspection_id, officer_headers)
        )
        assert meta["total_count"] == 1
        assert rows[0]["status"] == "OPEN"
        assert_money_cents(rows[0]["penalty_component_cents"], 60000)
        assert build.read_store(store_id)["failed_audit_count_30d"] == 0
