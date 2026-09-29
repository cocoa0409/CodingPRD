"""Parallel and cyclic state shapes, and the two cascades that run in opposite directions."""

from test_helpers import (
    assert_instant_is,
    assert_pct,
    assert_posture,
    expected_occurrence_weighted_score,
    factories,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_AUDIT_INVALID_STATE,
    ERR_LABEL_NOT_PRINTED,
    ERR_LABEL_TASK_INVALID_STATE,
    ERR_TRANSITION_ALREADY_APPLIED,
)
from test_helpers.constants import (
    ROLE_CODE_LABEL_ASSOCIATE,
    ROLE_CODE_PRICE_AUDITOR,
)

MILK_1_GAL = {
    "item_upc": "00000000000201",
    "item_description": "Milk 1gal",
    "category_code": "DAIRY",
    "old_retail_cents": 449,
    "new_retail_cents": 399,
    "net_content_qty": 1,
    "net_content_uom": "GAL",
}
YOGURT_6_CT = {
    "item_upc": "00000000000202",
    "item_description": "Yogurt 6ct",
    "category_code": "DAIRY",
    "old_retail_cents": 599,
    "new_retail_cents": 549,
    "net_content_qty": 6,
    "net_content_uom": "CT",
}

FOUR_LINES_ONE_OVERCHARGE = [
    {
        "item_upc": "00000000000101",
        "shelf_price_cents": 949,
        "register_price_cents": 1099,
    },
    {
        "item_upc": "00000000000102",
        "shelf_price_cents": 299,
        "register_price_cents": 299,
    },
    {
        "item_upc": "00000000000103",
        "shelf_price_cents": 199,
        "register_price_cents": 199,
    },
    {
        "item_upc": "00000000000104",
        "shelf_price_cents": 399,
        "register_price_cents": 399,
    },
]
FIFTH_MATCHING_LINE = {
    "item_upc": "00000000000105",
    "shelf_price_cents": 259,
    "register_price_cents": 259,
}


class TestLabelTaskParallelAxes:
    def test_seven_ordered_calls_walk_both_axes_without_either_implying_the_other(
        self, api, build
    ):
        """Print moves one axis, place the other, and rejection splits them apart again.

        PRD 3.4: "The two axes are genuinely independent, and no transition on one
        implies a transition on the other."
        PRD 3.4: "Placement requires the print axis to read exactly `PRINTED` — a task
        that was rejected and consequently needs reprinting cannot simply be
        re-placed, and the attempt is refused with `ERR_LABEL_NOT_PRINTED`."
        PRD 3.4: "`due_at` is the effective date of the batch that owns the line,
        advanced by the jurisdiction's grace period in hours — with the default grace
        period that is two days after the price becomes binding."
        PRD 3.4: "Printing also advances the underlying line `TASKED → LABELED` when
        the line is in `TASKED`."
        PRD 3.4: "The placement axis is untouched by printing."
        PRD 3.4: "On success, `placed_by_associate_id` is stamped from `X-User-ID` and
        `placed_at` from the current instant, the store's label backlog is recomputed
        and then its posture recomputed, and when the underlying line sits in `FAILED`
        it moves `FAILED → LABELED`."
        PRD 3.4: "It increments `rejection_count` by one, pushes the print axis from
        `PRINTED` back to `REPRINT_REQUIRED`, and pushes the underlying line `LABELED →
        FAILED`."
        PRD 3.4: "When `rejection_count` reaches 2, it additionally creates an
        accountability action against the associate named by `placed_by_associate_id`
        — with `trigger_code` `VERIFICATION_REJECTED`, `action_type` `COACHING`, and
        `issued_by_ref` set to the literal `system` — which immediately re-derives
        that associate's score and may suspend them and reset their other placed
        tasks, exactly as §3.2 describes."
        PRD 3.4: "It stamps `verified_by_associate_id` from `X-User-ID` and
        `verified_at` from the current instant, and stores the observed shelf price as
        the verifier's reading."
        PRD 3.3: "A batch in `PARTIALLY_EXECUTED` advances `PARTIALLY_EXECUTED →
        EXECUTED` the moment a line's move into `VERIFIED` makes the verified-line
        count equal the line count, provided the line count is at least 1."

        Design: Difficulty/non_linear_state_machine/label_task_parallel_print_and_placement_axes_advance_independently
        """
        jurisdiction_id = build.jurisdiction(
            code="US-CA",
            name="California",
            grace_period_hours=48,
            unit_price_uom_rule="PER_SINGLE_ITEM",
        )
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        aisle_id = build.aisle(store_id, aisle_code="A01", category_code="DAIRY")
        associate_id = build.certified(
            store_id,
            ROLE_CODE_LABEL_ASSOCIATE,
            employee_number="E-LA1",
            full_name="Lena Label",
        )
        auditor_id = build.certified(
            store_id,
            ROLE_CODE_PRICE_AUDITOR,
            module_code="AUDIT_101",
            employee_number="E-PA1",
            full_name="Pat Auditor",
        )
        associate_headers = build.associate_headers(associate_id)
        auditor_headers = build.auditor(auditor_id)

        built = build.distributed_file(
            jurisdiction_id,
            [store_id],
            [MILK_1_GAL, YOGURT_6_CT],
            file_number="PCF-1001",
            priority="ROUTINE",
        )
        first_line, second_line = built["line_ids"]
        task = build.label_task(
            built["file_id"],
            store_id,
            first_line,
            aisle_id,
            associate_id,
            "2026-08-03T09:00:00Z",
            "2026-08-03T11:00:00Z",
            built["version"],
        )
        task_id = task["id"]

        assert task["print_status"] == "NOT_PRINTED"
        assert task["placement_status"] == "UNPLACED"
        assert_instant_is(task["due_at"], "2026-08-05T00:00:00Z")
        assert task["overdue"] is False
        assert task["rejection_count"] == 0
        assert task["printed_label_serial"] is None

        validate_error(
            api.place_label_task(
                task_id, factories.place_payload(399), associate_headers
            ),
            ERR_LABEL_NOT_PRINTED,
            409,
        )
        untouched = build.read_task(task_id)
        assert untouched["print_status"] == "NOT_PRINTED"
        assert untouched["placement_status"] == "UNPLACED"

        printed = build.print_task(task_id, associate_headers)
        assert printed["print_status"] == "PRINTED"
        assert printed["placement_status"] == "UNPLACED"
        assert printed["printed_label_serial"] is not None
        assert build.read_line(first_line)["line_status"] == "LABELED"

        placed = build.place_task(task_id, 399, associate_headers)
        assert placed["placement_status"] == "PLACED"
        assert placed["print_status"] == "PRINTED"
        assert placed["placed_by_associate_id"] == associate_id
        assert_instant_is(placed["placed_at"], "2026-08-01T00:00:00Z")

        rejected = build.verify_task(
            task_id,
            auditor_headers,
            outcome="REJECTED",
            rejection_reason="Tag hung on the wrong facing",
        )
        assert rejected["placement_status"] == "REJECTED"
        assert rejected["print_status"] == "REPRINT_REQUIRED"
        assert rejected["rejection_count"] == 1
        assert rejected["printed_label_serial"] is None
        assert build.read_line(first_line)["line_status"] == "FAILED"

        actions, meta = validate_paginated(
            api.list_associate_accountability_actions(
                associate_id, build.associate_headers(associate_id)
            )
        )
        assert meta["total_count"] == 0
        assert actions == []

        reprinted = build.print_task(task_id, associate_headers)
        assert reprinted["print_status"] == "PRINTED"
        assert reprinted["placement_status"] == "REJECTED"
        assert build.read_line(first_line)["line_status"] == "FAILED"

        replaced = build.place_task(task_id, 399, associate_headers)
        assert replaced["placement_status"] == "PLACED"
        assert replaced["print_status"] == "PRINTED"
        assert build.read_line(first_line)["line_status"] == "LABELED"

        verified = build.verify_task(task_id, auditor_headers)
        assert verified["placement_status"] == "VERIFIED"
        assert verified["print_status"] == "PRINTED"
        assert verified["verified_by_associate_id"] == auditor_id
        assert build.read_line(first_line)["line_status"] == "VERIFIED"

        file_record = build.read_file(built["file_id"])
        assert file_record["status"] == "PARTIALLY_EXECUTED"
        assert file_record["verified_line_count"] == 1
        assert file_record["line_count"] == 2
        assert build.read_line(second_line)["line_status"] == "PENDING"

        assert build.read_associate(associate_id)["verified_placement_count"] == 1
        store = build.read_store(store_id)
        assert store["label_backlog_count"] == 0
        assert_posture(store, "OPEN")

    def test_each_axis_keeps_its_own_guard_and_the_reprint_serial_is_reminted(
        self, api, build
    ):
        """The placement guard reads the print axis twice, from two different print states.

        PRD 3.4: "The two axes are genuinely independent, and no transition on one
        implies a transition on the other."
        PRD 3.4: "The **print axis** takes `NOT_PRINTED`, `PRINTED` and
        `REPRINT_REQUIRED` and has no terminal state — a tag can always need
        reprinting."
        PRD 3.4: "On success a `printed_label_serial` is minted as the literal prefix
        `LBL-` followed by a zero-padded print sequence number maintained per store,
        and the same per-store sequence supplies the re-minted serial on a reprint."
        PRD 3.4: "Placement requires the print axis to read exactly `PRINTED` — a task
        that was rejected and consequently needs reprinting cannot simply be
        re-placed, and the attempt is refused with `ERR_LABEL_NOT_PRINTED`."
        PRD 3.4: "Both outcomes require the placement axis to read exactly `PLACED`,
        refusing an `UNPLACED` task with `ERR_LABEL_TASK_INVALID_STATE` and a second
        verification of an already-`VERIFIED` task with
        `ERR_TRANSITION_ALREADY_APPLIED`."
        PRD 3.4: "When `rejection_count` reaches 2, it additionally creates an
        accountability action against the associate named by `placed_by_associate_id`
        — with `trigger_code` `VERIFICATION_REJECTED`, `action_type` `COACHING`, and
        `issued_by_ref` set to the literal `system` — which immediately re-derives
        that associate's score and may suspend them and reset their other placed
        tasks, exactly as §3.2 describes."
        PRD 3.2: "Under `OCCURRENCE_WEIGHTED`, the score is 100 reduced by the sum of
        the weights of the outstanding actions, floored at zero — each issued action
        costs its flat weight regardless of how much correct work the associate has
        done."
        PRD 3.4: "The `PLACED → REJECTED → PLACED` revision loop on this axis may
        repeat without bound."

        Design: Difficulty/non_linear_state_machine/label_task_parallel_print_and_placement_axes_advance_independently
        """
        jurisdiction_id = build.jurisdiction(
            code="US-CA",
            name="California",
            grace_period_hours=48,
            unit_price_uom_rule="PER_SINGLE_ITEM",
        )
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        aisle_id = build.aisle(store_id, aisle_code="A01", category_code="DAIRY")
        associate_id = build.certified(
            store_id,
            ROLE_CODE_LABEL_ASSOCIATE,
            employee_number="E-LA1",
            full_name="Lena Label",
        )
        auditor_id = build.certified(
            store_id,
            ROLE_CODE_PRICE_AUDITOR,
            module_code="AUDIT_101",
            employee_number="E-PA1",
            full_name="Pat Auditor",
        )
        associate_headers = build.associate_headers(associate_id)
        auditor_headers = build.auditor(auditor_id)

        built = build.distributed_file(
            jurisdiction_id,
            [store_id],
            [MILK_1_GAL],
            file_number="PCF-1001",
            priority="ROUTINE",
        )
        task_id = build.label_task(
            built["file_id"],
            store_id,
            built["line_ids"][0],
            aisle_id,
            associate_id,
            "2026-08-03T09:00:00Z",
            "2026-08-03T11:00:00Z",
            built["version"],
        )["id"]

        first_serial = build.print_task(task_id, associate_headers)[
            "printed_label_serial"
        ]
        assert first_serial.startswith("LBL-")
        validate_error(
            api.verify_label_task_placement(
                task_id, factories.verify_payload("VERIFIED"), auditor_headers
            ),
            ERR_LABEL_TASK_INVALID_STATE,
            409,
        )
        still_printed = build.read_task(task_id)
        assert still_printed["print_status"] == "PRINTED"
        assert still_printed["placement_status"] == "UNPLACED"

        build.place_task(task_id, 399, associate_headers)
        first_rejection = build.verify_task(
            task_id,
            auditor_headers,
            outcome="REJECTED",
            rejection_reason="Tag hung on the wrong facing",
        )
        assert first_rejection["rejection_count"] == 1
        assert first_rejection["print_status"] == "REPRINT_REQUIRED"

        validate_error(
            api.place_label_task(
                task_id, factories.place_payload(399), associate_headers
            ),
            ERR_LABEL_NOT_PRINTED,
            409,
        )
        assert build.read_task(task_id)["placement_status"] == "REJECTED"

        second_serial = build.print_task(task_id, associate_headers)[
            "printed_label_serial"
        ]
        assert second_serial.startswith("LBL-")
        assert second_serial != first_serial

        build.place_task(task_id, 399, associate_headers)
        second_rejection = build.verify_task(
            task_id,
            auditor_headers,
            outcome="REJECTED",
            rejection_reason="Facing still wrong after the reprint",
        )
        assert second_rejection["rejection_count"] == 2
        assert second_rejection["placement_status"] == "REJECTED"
        assert second_rejection["print_status"] == "REPRINT_REQUIRED"

        actions, meta = validate_paginated(
            api.list_associate_accountability_actions(associate_id, associate_headers)
        )
        assert meta["total_count"] == 1
        assert actions[0]["action_type"] == "COACHING"
        assert actions[0]["trigger_code"] == "VERIFICATION_REJECTED"
        assert actions[0]["issued_by_ref"] == "system"
        assert actions[0]["status"] == "ISSUED"
        assert actions[0]["score_weight"] == 5
        assert actions[0]["associate_id"] == associate_id

        associate = build.read_associate(associate_id)
        assert_pct(
            associate["accountability_score"],
            expected_occurrence_weighted_score(["COACHING"]),
        )
        assert associate["training_status"] == "CERTIFIED"

        build.print_task(task_id, associate_headers)
        build.place_task(task_id, 399, associate_headers)
        verified = build.verify_task(task_id, auditor_headers)
        assert verified["placement_status"] == "VERIFIED"
        assert verified["print_status"] == "PRINTED"
        assert verified["rejection_count"] == 2

        validate_error(
            api.verify_label_task_placement(
                task_id, factories.verify_payload("VERIFIED"), auditor_headers
            ),
            ERR_TRANSITION_ALREADY_APPLIED,
            409,
        )
        final = build.read_task(task_id)
        assert final["placement_status"] == "VERIFIED"
        assert final["print_status"] == "PRINTED"
        assert build.read_file(built["file_id"])["status"] == "EXECUTED"


class TestScannerAuditCloseReopenCycle:
    def test_the_second_close_recomputes_the_verdict_from_the_enlarged_sample(
        self, api, build
    ):
        """25.00 FAIL on four lines becomes 20.00 PASS on five, with reopen_count stuck at 1.

        PRD 3.5: "The first observation appended to an `OPEN` audit moves the audit
        `OPEN → SCANNING`; an observation appended while the audit sits in `REOPENED`
        moves it `REOPENED → SCANNING`, closing the audit's re-scanning cycle."
        PRD 3.5: "The sample size is the count of every scan line belonging to the
        audit, with no status filter of any kind, because the evidence is immutable and
        therefore the set is exactly what was posted."
        PRD 3.5: "The **gross mismatch** rate, stored as `gross_error_rate_pct`, is the
        overcharge count plus the undercharge count, divided by the sample size,
        multiplied by 100, and rounded half up to two decimal places."
        PRD 3.5: "The `outcome` becomes `FAIL` when `error_rate_pct` is at or above
        `scanner_error_rate_threshold_pct`, and `PASS` otherwise — the comparison is
        inclusive, so a rate exactly equal to the threshold fails."
        PRD 3.5: "Closing also stamps `closed_at` with the current instant and
        refreshes the audited aisle's `last_audit_closed_at` to the same instant."
        PRD 3.5: "On success the verdict is withdrawn: `outcome` returns to `PENDING`,
        and `error_rate_pct`, `rate_variant_applied`, `gross_error_rate_pct`,
        `net_overcharge_rate_pct` and `closed_at` all return to null."
        PRD 3.5: "`reopen_count` rises by one."
        PRD 3.5: "The store's `failed_audit_count_30d` is then recomputed and its
        posture recomputed — a reopened failure leaves the posture inputs, so reopening
        can relax a frozen store back to restricted or open until the audit closes
        again."
        PRD 3.5: "When the aisle has no assigned associate, or the referenced associate
        is already `SUSPENDED`, **no accountability action is created at all**: the
        audit still closes with `FAIL`, the store's failed-audit count still rises and
        its posture is still recomputed, and the failure is simply unattributed."

        Design: Difficulty/non_linear_state_machine/scanner_audit_close_reopen_close_cycle_recomputes_outcome
        """
        jurisdiction_id = build.jurisdiction(
            code="US-CA",
            name="California",
            scanner_error_rate_threshold_pct=25.0,
            default_rate_variant="GROSS_MISMATCH",
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
        built = build.audit_with_scan_lines(
            store_id,
            aisle_id,
            auditor_id,
            FOUR_LINES_ONE_OVERCHARGE,
            scan_window_start="2026-08-01T08:00:00Z",
            scan_window_end="2026-08-01T10:00:00Z",
        )
        audit_id = built["audit_id"]
        assert build.read_audit(audit_id)["status"] == "SCANNING"

        first_close = build.close_audit(audit_id, auditor_headers)
        assert first_close["status"] == "CLOSED"
        assert first_close["sample_size"] == 4
        assert first_close["overcharge_count"] == 1
        assert first_close["undercharge_count"] == 0
        assert_pct(first_close["gross_error_rate_pct"], 25.00)
        assert_pct(first_close["error_rate_pct"], 25.00)
        assert first_close["outcome"] == "FAIL"
        assert first_close["rate_variant_applied"] == "GROSS_MISMATCH"
        assert_instant_is(first_close["closed_at"], "2026-08-01T00:00:00Z")
        assert_instant_is(
            build.read_aisle(aisle_id)["last_audit_closed_at"],
            "2026-08-01T00:00:00Z",
        )

        failed_once = build.read_store(store_id)
        assert failed_once["failed_audit_count_30d"] == 1
        assert_posture(failed_once, "RESTRICTED")

        reopened = build.reopen_audit(
            audit_id, "Auditor sampled only half the aisle"
        )
        assert reopened["status"] == "REOPENED"
        assert reopened["outcome"] == "PENDING"
        assert reopened["error_rate_pct"] is None
        assert reopened["gross_error_rate_pct"] is None
        assert reopened["net_overcharge_rate_pct"] is None
        assert reopened["rate_variant_applied"] is None
        assert reopened["closed_at"] is None
        assert reopened["reopen_count"] == 1

        withdrawn = build.read_store(store_id)
        assert withdrawn["failed_audit_count_30d"] == 0
        assert_posture(withdrawn, "OPEN")

        build.scan_line(
            audit_id,
            FIFTH_MATCHING_LINE["item_upc"],
            FIFTH_MATCHING_LINE["shelf_price_cents"],
            FIFTH_MATCHING_LINE["register_price_cents"],
            auditor_headers,
        )
        rescanning = build.read_audit(audit_id)
        assert rescanning["status"] == "SCANNING"
        assert rescanning["reopen_count"] == 1

        second_close = build.close_audit(audit_id, auditor_headers)
        assert second_close["status"] == "CLOSED"
        assert second_close["sample_size"] == 5
        assert second_close["overcharge_count"] == 1
        assert_pct(second_close["gross_error_rate_pct"], 20.00)
        assert_pct(second_close["error_rate_pct"], 20.00)
        assert second_close["outcome"] == "PASS"
        assert second_close["reopen_count"] == 1

        settled = build.read_store(store_id)
        assert settled["failed_audit_count_30d"] == 0
        assert_posture(settled, "OPEN")

        actions, meta = validate_paginated(
            api.list_associate_accountability_actions(auditor_id, auditor_headers)
        )
        assert meta["total_count"] == 0
        assert actions == []

    def test_the_cycle_may_repeat_and_each_state_refuses_the_calls_that_are_not_its_own(
        self, api, build
    ):
        """A close straight out of REOPENED restates the same verdict; only a new line changes it.

        PRD 3.5: "Closing moves the audit `SCANNING → CLOSED` or `REOPENED → CLOSED` —
        the two source states behave identically — and it is what stamps the verdict."
        PRD 3.5: "Closing a second time is refused with
        `ERR_TRANSITION_ALREADY_APPLIED`."
        PRD 3.5: "Appending to a `CLOSED` audit is refused with
        `ERR_AUDIT_INVALID_STATE`."
        PRD 3.5: "Reopening is refused with `ERR_AUDIT_INVALID_STATE` when the audit is
        not `CLOSED`, and also when any regulatory inspection using this audit as its
        evidence of record has already reached `CLOSED` — evidence that has been
        adjudicated cannot be retroactively rewritten."
        PRD 3.5: "`reopen_count` rises by one."
        PRD 3.5: "The audit then walks `CLOSED → REOPENED → SCANNING → CLOSED`, and
        that cycle may repeat."
        PRD 3.5: "The `outcome` becomes `FAIL` when `error_rate_pct` is at or above
        `scanner_error_rate_threshold_pct`, and `PASS` otherwise — the comparison is
        inclusive, so a rate exactly equal to the threshold fails."
        PRD 3.5: "The store's `failed_audit_count_30d` is then recomputed and its
        posture recomputed — a reopened failure leaves the posture inputs, so reopening
        can relax a frozen store back to restricted or open until the audit closes
        again."

        Design: Difficulty/non_linear_state_machine/scanner_audit_close_reopen_close_cycle_recomputes_outcome
        """
        jurisdiction_id = build.jurisdiction(
            code="US-CA",
            name="California",
            scanner_error_rate_threshold_pct=25.0,
            default_rate_variant="GROSS_MISMATCH",
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
        built = build.audit_with_scan_lines(
            store_id,
            aisle_id,
            auditor_id,
            FOUR_LINES_ONE_OVERCHARGE,
            scan_window_start="2026-08-01T08:00:00Z",
            scan_window_end="2026-08-01T10:00:00Z",
        )
        audit_id = built["audit_id"]

        first_close = build.close_audit(audit_id, auditor_headers)
        assert first_close["outcome"] == "FAIL"
        assert_pct(first_close["error_rate_pct"], 25.00)

        validate_error(
            api.create_scan_line(
                audit_id,
                factories.scan_line_payload("00000000000106", 100, 100),
                auditor_headers,
            ),
            ERR_AUDIT_INVALID_STATE,
            409,
        )
        validate_error(
            api.close_scanner_audit(audit_id, auditor_headers),
            ERR_TRANSITION_ALREADY_APPLIED,
            409,
        )
        assert build.read_audit(audit_id)["sample_size"] == 4

        first_reopen = build.reopen_audit(audit_id, "Register export was incomplete")
        assert first_reopen["status"] == "REOPENED"
        assert first_reopen["reopen_count"] == 1
        validate_error(
            api.reopen_scanner_audit(
                audit_id,
                factories.reopen_audit_payload("Second thoughts on the sample"),
                build.officer,
            ),
            ERR_AUDIT_INVALID_STATE,
            409,
        )

        restated = build.close_audit(audit_id, auditor_headers)
        assert restated["status"] == "CLOSED"
        assert restated["sample_size"] == 4
        assert_pct(restated["error_rate_pct"], 25.00)
        assert restated["outcome"] == "FAIL"
        assert restated["reopen_count"] == 1
        assert_instant_is(restated["closed_at"], "2026-08-01T00:00:00Z")
        restricted = build.read_store(store_id)
        assert restricted["failed_audit_count_30d"] == 1
        assert_posture(restricted, "RESTRICTED")

        second_reopen = build.reopen_audit(audit_id, "Aisle was only half walked")
        assert second_reopen["reopen_count"] == 2
        assert second_reopen["outcome"] == "PENDING"
        assert second_reopen["closed_at"] is None
        relaxed = build.read_store(store_id)
        assert relaxed["failed_audit_count_30d"] == 0
        assert_posture(relaxed, "OPEN")

        build.scan_line(
            audit_id,
            FIFTH_MATCHING_LINE["item_upc"],
            FIFTH_MATCHING_LINE["shelf_price_cents"],
            FIFTH_MATCHING_LINE["register_price_cents"],
            auditor_headers,
        )
        assert build.read_audit(audit_id)["status"] == "SCANNING"

        final = build.close_audit(audit_id, auditor_headers)
        assert final["sample_size"] == 5
        assert_pct(final["error_rate_pct"], 20.00)
        assert final["outcome"] == "PASS"
        assert final["reopen_count"] == 2
        assert final["status"] == "CLOSED"
        reconciled = validate_success(
            api.get_store_compliance_summary(store_id, build.officer)
        )
        assert reconciled["failed_audit_count_30d"] == 0
        assert_posture(reconciled, "OPEN")


BUTTER_1_LB = {
    "item_upc": "00000000000302",
    "item_description": "Butter 1lb",
    "category_code": "DAIRY",
    "old_retail_cents": 549,
    "new_retail_cents": 499,
    "net_content_qty": 1,
    "net_content_uom": "LB",
}
CHEESE_8_OZ = {
    "item_upc": "00000000000303",
    "item_description": "Cheese 8oz",
    "category_code": "DAIRY",
    "old_retail_cents": 399,
    "new_retail_cents": 349,
    "net_content_qty": 8,
    "net_content_uom": "OZ",
}
MILK_HOP_LINE = {
    "item_upc": "00000000000301",
    "item_description": "Milk 1gal",
    "category_code": "DAIRY",
    "old_retail_cents": 449,
    "new_retail_cents": 399,
    "net_content_qty": 1,
    "net_content_uom": "GAL",
}


class TestVerificationCompletionCascade:
    def test_one_verify_climbs_task_line_file_store_while_the_two_line_file_stops_at_the_line(
        self, api, build
    ):
        """The intermediate hop is proved necessary by a file whose second line has no task.

        PRD 3.4: "It then advances the underlying line `LABELED → VERIFIED` (hop two),
        which re-derives the batch's verified-line count and may complete the batch
        (hop three), which credits `executed_file_count` on every scoped store and
        re-derives their backlogs and postures (hop four)."
        PRD 3.3: "A batch in `PARTIALLY_EXECUTED` advances `PARTIALLY_EXECUTED →
        EXECUTED` the moment a line's move into `VERIFIED` makes the verified-line count
        equal the line count, provided the line count is at least 1."
        PRD 3.3: "The line count itself counts every line of the batch whose status is
        not `WITHDRAWN`, and the verified-line count counts those whose status is
        `VERIFIED` — which is why withdrawing lines can complete a batch that looked
        incomplete."
        PRD 3.3: "On completion, every store named in the batch's `scope_store_ids` has
        its `executed_file_count` raised by one, then its label backlog recomputed, then
        its posture recomputed, in that order."
        PRD 3.4: "Within the same request it also recomputes the **placer's**
        `verified_placement_count` — not the verifier's — because that counter feeds the
        task-weighted accountability variant, and it recomputes the store's label
        backlog and then its posture."
        PRD 2.7: "`executed_file_count` is the number of price change files that reached
        the executed state with this store in their scope."
        PRD 3.4: "Label tasks are discoverable through a single filtered list that
        collapses all six of the task's associate- and resource-valued references into
        query parameters: `store_id`, `price_change_line_id`, `aisle_id`,
        `assigned_associate_id`, `placed_by_associate_id` and
        `verified_by_associate_id`, plus `print_status`, `placement_status` and
        `overdue`."

        Design: Difficulty/transitive_cascade/verify_placement_cascades_task_to_line_to_file_to_store_posture
        """
        jurisdiction_id = build.jurisdiction(
            code="US-CA", name="California", grace_period_hours=48
        )
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        aisle_id = build.aisle(store_id, aisle_code="A01", category_code="DAIRY")
        associate_id = build.certified(
            store_id,
            ROLE_CODE_LABEL_ASSOCIATE,
            employee_number="E-LA1",
            full_name="Lena Label",
        )
        auditor_id = build.certified(
            store_id,
            ROLE_CODE_PRICE_AUDITOR,
            module_code="AUDIT_101",
            employee_number="E-PA1",
            full_name="Pat Auditor",
        )
        associate_headers = build.associate_headers(associate_id)
        auditor_headers = build.auditor(auditor_id)

        single = build.distributed_file(
            jurisdiction_id,
            [store_id],
            [MILK_HOP_LINE],
            file_number="PCF-1001",
            priority="ROUTINE",
        )
        single_task = build.placed_task(
            single["file_id"],
            store_id,
            single["line_ids"][0],
            aisle_id,
            associate_id,
            399,
            placer_headers=associate_headers,
            scheduled_start_at="2026-08-03T09:00:00Z",
            scheduled_end_at="2026-08-03T10:00:00Z",
        )

        pair = build.distributed_file(
            jurisdiction_id,
            [store_id],
            [BUTTER_1_LB, CHEESE_8_OZ],
            effective_date="2026-08-04T00:00:00Z",
            file_number="PCF-1002",
            priority="ROUTINE",
        )
        pair_task = build.placed_task(
            pair["file_id"],
            store_id,
            pair["line_ids"][0],
            aisle_id,
            associate_id,
            499,
            placer_headers=associate_headers,
            scheduled_start_at="2026-08-04T09:00:00Z",
            scheduled_end_at="2026-08-04T10:00:00Z",
        )

        before = build.read_store(store_id)
        assert before["label_backlog_count"] == 0
        assert before["executed_file_count"] == 0
        assert_posture(before, "OPEN")

        verified = build.verify_task(single_task["task_id"], auditor_headers)
        assert verified["placement_status"] == "VERIFIED"
        assert verified["verified_by_associate_id"] == auditor_id
        assert_instant_is(verified["verified_at"], "2026-08-01T00:00:00Z")
        assert build.read_line(single["line_ids"][0])["line_status"] == "VERIFIED"

        completed = build.read_file(single["file_id"])
        assert completed["verified_line_count"] == 1
        assert completed["line_count"] == 1
        assert completed["status"] == "EXECUTED"

        credited = build.read_store(store_id)
        assert credited["executed_file_count"] == 1
        assert credited["label_backlog_count"] == 0
        assert_posture(credited, "OPEN")

        control = build.verify_task(pair_task["task_id"], auditor_headers)
        assert control["placement_status"] == "VERIFIED"
        assert build.read_line(pair["line_ids"][0])["line_status"] == "VERIFIED"

        partial = build.read_file(pair["file_id"])
        assert partial["verified_line_count"] == 1
        assert partial["line_count"] == 2
        assert partial["status"] == "PARTIALLY_EXECUTED"
        assert build.read_line(pair["line_ids"][1])["line_status"] == "PENDING"

        after = build.read_store(store_id)
        assert after["executed_file_count"] == 1
        assert after["executed_file_count"] != 2

        assert build.read_associate(associate_id)["verified_placement_count"] == 2
        assert build.read_associate(auditor_id)["verified_placement_count"] == 0

        rows, meta = validate_paginated(
            api.list_label_tasks(
                build.admin,
                {"store_id": store_id, "placement_status": "VERIFIED"},
            )
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {
            single_task["task_id"],
            pair_task["task_id"],
        }

    def test_hop_four_fans_out_to_every_scoped_store_not_only_the_verifying_one(
        self, build
    ):
        """One line, two scoped stores, one verify — and both stores are credited.

        PRD 3.3: "When the task's placement is verified, the line moves `LABELED →
        VERIFIED`, which in turn re-derives the batch's verified-line count and may
        complete the batch."
        PRD 3.3: "On completion, every store named in the batch's `scope_store_ids` has
        its `executed_file_count` raised by one, then its label backlog recomputed, then
        its posture recomputed, in that order."
        PRD 3.4: "It then advances the underlying line `LABELED → VERIFIED` (hop two),
        which re-derives the batch's verified-line count and may complete the batch (hop
        three), which credits `executed_file_count` on every scoped store and re-derives
        their backlogs and postures (hop four)."
        PRD 3.4: "Within the same request it also recomputes the **placer's**
        `verified_placement_count` — not the verifier's — because that counter feeds the
        task-weighted accountability variant, and it recomputes the store's label
        backlog and then its posture."
        PRD 3.4: "and only one task may exist for any given line-and-store pair, a
        second attempt yielding `ERR_DUPLICATE_RESOURCE`."
        PRD 2.7: "`label_backlog_count` is the number of this store's label tasks whose
        placement axis is `UNPLACED` or `REJECTED` **and** whose underlying price change
        line is not `WITHDRAWN`."

        Design: Difficulty/transitive_cascade/verify_placement_cascades_task_to_line_to_file_to_store_posture
        """
        jurisdiction_id = build.jurisdiction(
            code="US-CA", name="California", grace_period_hours=48
        )
        first_store = build.store(
            jurisdiction_id, store_number="S001", name="Bay Street"
        )
        second_store = build.store(
            jurisdiction_id, store_number="S002", name="Elm Street"
        )
        first_aisle = build.aisle(first_store, aisle_code="A01", category_code="DAIRY")
        second_aisle = build.aisle(second_store, aisle_code="B01", category_code="DAIRY")
        first_associate = build.certified(
            first_store,
            ROLE_CODE_LABEL_ASSOCIATE,
            employee_number="E-LA1",
            full_name="Lena Label",
        )
        second_associate = build.certified(
            second_store,
            ROLE_CODE_LABEL_ASSOCIATE,
            employee_number="E-LA2",
            full_name="Nina Label",
        )
        first_auditor = build.certified(
            first_store,
            ROLE_CODE_PRICE_AUDITOR,
            module_code="AUDIT_101",
            employee_number="E-PA1",
            full_name="Pat Auditor",
        )

        built = build.distributed_file(
            jurisdiction_id,
            [first_store, second_store],
            [MILK_HOP_LINE],
            file_number="PCF-1001",
            priority="ROUTINE",
        )
        line_id = built["line_ids"][0]
        first_task = build.placed_task(
            built["file_id"],
            first_store,
            line_id,
            first_aisle,
            first_associate,
            399,
            scheduled_start_at="2026-08-03T09:00:00Z",
            scheduled_end_at="2026-08-03T10:00:00Z",
        )
        second_task = build.placed_task(
            built["file_id"],
            second_store,
            line_id,
            second_aisle,
            second_associate,
            399,
            scheduled_start_at="2026-08-03T09:00:00Z",
            scheduled_end_at="2026-08-03T10:00:00Z",
        )
        assert second_task["task"]["placement_status"] == "PLACED"
        assert build.read_file(built["file_id"])["status"] == "PARTIALLY_EXECUTED"

        verified = build.verify_task(
            first_task["task_id"], build.auditor(first_auditor)
        )
        assert verified["placement_status"] == "VERIFIED"
        assert build.read_line(line_id)["line_status"] == "VERIFIED"

        completed = build.read_file(built["file_id"])
        assert completed["verified_line_count"] == 1
        assert completed["line_count"] == 1
        assert completed["status"] == "EXECUTED"

        first_record = build.read_store(first_store)
        assert first_record["executed_file_count"] == 1
        assert first_record["label_backlog_count"] == 0
        assert_posture(first_record, "OPEN")

        second_record = build.read_store(second_store)
        assert second_record["executed_file_count"] == 1
        assert second_record["label_backlog_count"] == 0
        assert_posture(second_record, "OPEN")

        untouched = build.read_task(second_task["task_id"])
        assert untouched["placement_status"] == "PLACED"
        assert untouched["print_status"] == "PRINTED"

        assert build.read_associate(first_associate)["verified_placement_count"] == 1
        assert build.read_associate(second_associate)["verified_placement_count"] == 0
        assert build.read_associate(first_auditor)["verified_placement_count"] == 0


class TestAuditFailurePunitiveCascade:
    def test_one_close_suspends_the_associate_and_pushes_their_placed_task_back(
        self, api, build
    ):
        """Five hops downward from a single close: action, score, suspension, revert, store.

        PRD 3.5: "The candidate is not searched for: it is exactly the audited aisle's
        `assigned_associate_id`, referenced explicitly."
        PRD 3.5: "If the candidate already has at least one accountability action with
        status `ISSUED` and `action_type` `WRITTEN_WARNING`, the new action's
        `action_type` is `SUSPENSION`."
        PRD 3.5: "The action is created with its `associate_id` set to the accountable
        candidate just selected, its `trigger_code` set to `AUDIT_FAIL`, and its
        `issued_by_ref` set to the literal `system`."
        PRD 3.5: "The second hop recomputes the candidate's `issued_action_count` and
        `accountability_score`."
        PRD 3.5: "The third hop applies the derived suspension: if the recomputed score
        is strictly below the floor of 80, the associate transitions `CERTIFIED →
        SUSPENDED`."
        PRD 3.2: "The weight assigned to an action by its `action_type` is 5 for
        `COACHING`, 10 for `RETRAINING_ASSIGNED`, 15 for `WRITTEN_WARNING` and 25 for
        `SUSPENSION`, and that weight is stored on the action itself as `score_weight`."
        PRD 3.2: "Every label task assigned to them whose placement axis reads `PLACED`
        is pushed back — its placement axis returns from `PLACED` to `UNPLACED`, its
        `placed_by_associate_id` and `placed_at` are both cleared to null, and its print
        axis is pushed from `PRINTED` back to `REPRINT_REQUIRED` with
        `printed_label_serial` cleared to null."
        PRD 3.5: "Finally, independently of whether any action was created, the store's
        `failed_audit_count_30d` is recomputed and then its posture recomputed, in that
        order."
        PRD 2.7: "Otherwise the posture becomes `RESTRICTED` when the open finding count
        is at least 1, **or** when the thirty-day failed-audit count is exactly 1, **or**
        when the label backlog is at least 5, **or** when at least one signage violation
        exists."

        Design: Difficulty/transitive_cascade/audit_fail_cascades_action_to_associate_suspension_to_task_revert_to_store
        """
        jurisdiction_id = build.jurisdiction(
            code="US-CA",
            name="California",
            scanner_error_rate_threshold_pct=25.0,
            default_rate_variant="GROSS_MISMATCH",
            accountability_variant="OCCURRENCE_WEIGHTED",
        )
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        associate_id = build.certified(
            store_id,
            ROLE_CODE_LABEL_ASSOCIATE,
            employee_number="E-LA1",
            full_name="Lena Label",
        )
        auditor_id = build.certified(
            store_id,
            ROLE_CODE_PRICE_AUDITOR,
            module_code="AUDIT_101",
            employee_number="E-PA1",
            full_name="Pat Auditor",
        )
        aisle_id = build.aisle(
            store_id,
            aisle_code="A01",
            category_code="DAIRY",
            assigned_associate_id=associate_id,
        )
        associate_headers = build.associate_headers(associate_id)
        auditor_headers = build.auditor(auditor_id)

        warning = build.issue_action(associate_id, "WRITTEN_WARNING")
        assert warning["score_weight"] == 15
        assert warning["status"] == "ISSUED"

        built = build.distributed_file(
            jurisdiction_id,
            [store_id],
            [MILK_HOP_LINE],
            file_number="PCF-1001",
            priority="ROUTINE",
        )
        task = build.placed_task(
            built["file_id"],
            store_id,
            built["line_ids"][0],
            aisle_id,
            associate_id,
            399,
            placer_headers=associate_headers,
            scheduled_start_at="2026-08-03T09:00:00Z",
            scheduled_end_at="2026-08-03T10:00:00Z",
        )
        task_id = task["task_id"]

        before_associate = build.read_associate(associate_id)
        assert_pct(
            before_associate["accountability_score"],
            expected_occurrence_weighted_score(["WRITTEN_WARNING"]),
        )
        assert before_associate["training_status"] == "CERTIFIED"
        assert before_associate["issued_action_count"] == 1

        before_task = build.read_task(task_id)
        assert before_task["print_status"] == "PRINTED"
        assert before_task["placement_status"] == "PLACED"
        before_store = build.read_store(store_id)
        assert before_store["label_backlog_count"] == 0
        assert_posture(before_store, "OPEN")

        evidence = build.audit_with_scan_lines(
            store_id,
            aisle_id,
            auditor_id,
            FOUR_LINES_ONE_OVERCHARGE,
            scan_window_start="2026-08-01T08:00:00Z",
            scan_window_end="2026-08-01T10:00:00Z",
        )
        closed = build.close_audit(evidence["audit_id"], auditor_headers)
        assert closed["sample_size"] == 4
        assert closed["overcharge_count"] == 1
        assert_pct(closed["error_rate_pct"], 25.00)
        assert closed["outcome"] == "FAIL"

        actions, meta = validate_paginated(
            api.list_associate_accountability_actions(
                associate_id, build.officer, {"status": "ISSUED"}
            )
        )
        assert meta["total_count"] == 2
        cascaded = [row for row in actions if row["trigger_code"] == "AUDIT_FAIL"]
        assert len(cascaded) == 1
        assert cascaded[0]["action_type"] == "SUSPENSION"
        assert cascaded[0]["associate_id"] == associate_id
        assert cascaded[0]["issued_by_ref"] == "system"
        assert cascaded[0]["status"] == "ISSUED"
        assert cascaded[0]["score_weight"] == 25

        after_associate = build.read_associate(associate_id)
        assert after_associate["issued_action_count"] == 2
        assert_pct(
            after_associate["accountability_score"],
            expected_occurrence_weighted_score(["WRITTEN_WARNING", "SUSPENSION"]),
        )
        assert_pct(after_associate["accountability_score"], 60.00)
        assert after_associate["training_status"] == "SUSPENDED"

        reverted = build.read_task(task_id)
        assert reverted["placement_status"] == "UNPLACED"
        assert reverted["print_status"] == "REPRINT_REQUIRED"
        assert reverted["placed_by_associate_id"] is None
        assert reverted["placed_at"] is None
        assert reverted["printed_label_serial"] is None
        assert build.read_line(built["line_ids"][0])["line_status"] == "LABELED"

        after_store = build.read_store(store_id)
        assert after_store["label_backlog_count"] == 1
        assert after_store["failed_audit_count_30d"] == 1
        assert_posture(after_store, "RESTRICTED")

    def test_voiding_the_prior_warning_downgrades_the_selector_and_the_lower_hops_never_run(
        self, api, build
    ):
        """COACHING keeps the associate certified, so no task is pushed back; the doubled threshold picks the warning.

        PRD 3.2: "Alternatively a store manager or compliance officer voids it,
        supplying `target_status` of `VOIDED` together with a `void_reason`; voiding is
        the compensating operation for the accountability-score invariant, and after it
        the score returns to **exactly** its pre-issue value."
        PRD 3.5: "If the candidate already has at least one accountability action with
        status `ISSUED` and `action_type` `WRITTEN_WARNING`, the new action's
        `action_type` is `SUSPENSION`."
        PRD 3.5: "Otherwise, if the audit's applied `error_rate_pct` is at or above
        twice the jurisdiction's threshold — a doubled-threshold test that is likewise
        inclusive, so exactly 4.00 percent against a 2.00 percent threshold qualifies —
        the new action's `action_type` is `WRITTEN_WARNING`."
        PRD 3.5: "Otherwise it is `COACHING`."
        PRD 3.2: "The suspension floor is 80, and the comparison is **strict**: a
        recomputed score of exactly 80 does not suspend, a score of 79.99 does."
        PRD 3.2: "Only actions whose status is `ISSUED` count; `COMPLETED` and `VOIDED`
        actions never do."
        PRD 3.5: "Finally, independently of whether any action was created, the store's
        `failed_audit_count_30d` is recomputed and then its posture recomputed, in that
        order."
        PRD 2.7: "The posture becomes `FROZEN` when at least one escalated finding
        exists, **or** when the open finding count is at least 3, **or** when the
        thirty-day failed-audit count is at least 2."

        Design: Difficulty/transitive_cascade/audit_fail_cascades_action_to_associate_suspension_to_task_revert_to_store
        """
        jurisdiction_id = build.jurisdiction(
            code="US-CA",
            name="California",
            scanner_error_rate_threshold_pct=25.0,
            default_rate_variant="GROSS_MISMATCH",
            accountability_variant="OCCURRENCE_WEIGHTED",
        )
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        first_associate = build.certified(
            store_id,
            ROLE_CODE_LABEL_ASSOCIATE,
            employee_number="E-LA1",
            full_name="Lena Label",
        )
        second_associate = build.certified(
            store_id,
            ROLE_CODE_LABEL_ASSOCIATE,
            employee_number="E-LA2",
            full_name="Nina Label",
        )
        auditor_id = build.certified(
            store_id,
            ROLE_CODE_PRICE_AUDITOR,
            module_code="AUDIT_101",
            employee_number="E-PA1",
            full_name="Pat Auditor",
        )
        first_aisle = build.aisle(
            store_id,
            aisle_code="A01",
            category_code="DAIRY",
            assigned_associate_id=first_associate,
        )
        second_aisle = build.aisle(
            store_id,
            aisle_code="A02",
            category_code="BAKERY",
            assigned_associate_id=second_associate,
        )
        auditor_headers = build.auditor(auditor_id)

        warning = build.issue_action(first_associate, "WRITTEN_WARNING")
        assert_pct(build.read_associate(first_associate)["accountability_score"], 85.00)
        voided = build.void_action(warning["id"], "issued against the wrong associate")
        assert voided["status"] == "VOIDED"
        restored = build.read_associate(first_associate)
        assert_pct(restored["accountability_score"], 100.00)
        assert restored["training_status"] == "CERTIFIED"

        built = build.distributed_file(
            jurisdiction_id,
            [store_id],
            [MILK_HOP_LINE],
            file_number="PCF-1001",
            priority="ROUTINE",
        )
        task = build.placed_task(
            built["file_id"],
            store_id,
            built["line_ids"][0],
            first_aisle,
            first_associate,
            399,
            scheduled_start_at="2026-08-03T09:00:00Z",
            scheduled_end_at="2026-08-03T10:00:00Z",
        )
        task_id = task["task_id"]

        borderline = build.audit_with_scan_lines(
            store_id,
            first_aisle,
            auditor_id,
            FOUR_LINES_ONE_OVERCHARGE,
            scan_window_start="2026-08-01T08:00:00Z",
            scan_window_end="2026-08-01T10:00:00Z",
        )
        doubled = build.audit_with_scan_lines(
            store_id,
            second_aisle,
            auditor_id,
            [
                {
                    "item_upc": "00000000000501",
                    "shelf_price_cents": 349,
                    "register_price_cents": 499,
                },
                {
                    "item_upc": "00000000000502",
                    "shelf_price_cents": 249,
                    "register_price_cents": 399,
                },
            ],
            scan_window_start="2026-08-01T12:00:00Z",
            scan_window_end="2026-08-01T14:00:00Z",
        )

        first_close = build.close_audit(borderline["audit_id"], auditor_headers)
        assert_pct(first_close["error_rate_pct"], 25.00)
        assert first_close["outcome"] == "FAIL"

        coaching_rows, coaching_meta = validate_paginated(
            api.list_associate_accountability_actions(
                first_associate, build.officer, {"status": "ISSUED"}
            )
        )
        assert coaching_meta["total_count"] == 1
        assert coaching_rows[0]["action_type"] == "COACHING"
        assert coaching_rows[0]["trigger_code"] == "AUDIT_FAIL"
        assert coaching_rows[0]["score_weight"] == 5

        coached = build.read_associate(first_associate)
        assert_pct(
            coached["accountability_score"],
            expected_occurrence_weighted_score(["COACHING"]),
        )
        assert coached["training_status"] == "CERTIFIED"

        intact = build.read_task(task_id)
        assert intact["print_status"] == "PRINTED"
        assert intact["placement_status"] == "PLACED"
        assert intact["placed_by_associate_id"] == first_associate
        restricted = build.read_store(store_id)
        assert restricted["label_backlog_count"] == 0
        assert restricted["failed_audit_count_30d"] == 1
        assert_posture(restricted, "RESTRICTED")

        second_close = build.close_audit(doubled["audit_id"], auditor_headers)
        assert_pct(second_close["error_rate_pct"], 100.00)
        assert second_close["outcome"] == "FAIL"

        warned_rows, warned_meta = validate_paginated(
            api.list_associate_accountability_actions(
                second_associate, build.officer, {"status": "ISSUED"}
            )
        )
        assert warned_meta["total_count"] == 1
        assert warned_rows[0]["action_type"] == "WRITTEN_WARNING"
        assert warned_rows[0]["trigger_code"] == "AUDIT_FAIL"
        assert warned_rows[0]["issued_by_ref"] == "system"

        warned = build.read_associate(second_associate)
        assert_pct(
            warned["accountability_score"],
            expected_occurrence_weighted_score(["WRITTEN_WARNING"]),
        )
        assert warned["training_status"] == "CERTIFIED"

        frozen = build.read_store(store_id)
        assert frozen["failed_audit_count_30d"] == 2
        assert_posture(frozen, "FROZEN")

        all_rows, all_meta = validate_paginated(
            api.list_associate_accountability_actions(first_associate, build.officer)
        )
        assert all_meta["total_count"] == 2
        assert {row["status"] for row in all_rows} == {"ISSUED", "VOIDED"}
