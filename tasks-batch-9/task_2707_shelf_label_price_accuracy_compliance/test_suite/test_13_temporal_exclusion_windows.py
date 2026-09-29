"""Windows that exclude each other: aisle cooldowns, touching labour intervals and a daily cap."""

from test_helpers import (
    assert_instant_is,
    factories,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_AISLE_AUDIT_WINDOW_CONFLICT,
    ERR_ASSOCIATE_DAILY_CAP_EXCEEDED,
    ERR_ASSOCIATE_SCHEDULE_CONFLICT,
)
from test_helpers.constants import (
    ROLE_CODE_LABEL_ASSOCIATE,
    ROLE_CODE_PRICE_AUDITOR,
)


def _audit_window(api, store_id, aisle_id, auditor_id, headers, start, end):
    """One creation attempt for a scan window, returned unvalidated."""
    return api.create_scanner_audit(
        factories.scanner_audit_payload(store_id, aisle_id, auditor_id, start, end),
        headers,
    )


def _task_attempt(api, build, file_id, store_id, line_id, aisle_id, associate_id, start, end):
    """One label-task creation attempt on a freshly read file version, unvalidated."""
    return api.create_label_task(
        file_id,
        factories.label_task_payload(
            store_id,
            line_id,
            aisle_id,
            associate_id,
            start,
            end,
            build.file_version(file_id),
        ),
        build.admin,
    )


class TestAisleWindowCooldown:
    def test_the_cooldown_extends_the_incumbent_window_and_closing_it_gives_the_aisle_back(
        self, api, build, admin_headers
    ):
        """The refused minute, the free minute, and the slot that reappears once the walk is closed.

        PRD 2.9: "A conflict exists when the new window's start is earlier than an
        existing window's end plus 60 minutes **and** that existing window's start is
        earlier than the new window's end, considering only audits on the same aisle
        that are not `CLOSED`."
        PRD 3.5: "Each existing window on the same aisle is therefore extended by a
        60-minute cooldown after its end, and a new window conflicts when its start
        falls before that extended end **while** the existing window's start falls
        before the new window's end — considering only audits on that aisle which are
        not yet `CLOSED`."
        PRD 3.5: "A new audit starts in `OPEN` with `outcome` `PENDING`, with
        `sample_size`, `overcharge_count`, `undercharge_count` and `reopen_count` all
        0, and with `gross_error_rate_pct`, `net_overcharge_rate_pct`,
        `error_rate_pct`, `rate_variant_applied` and `closed_at` all null."
        PRD 3.5: "Closing also stamps `closed_at` with the current instant and
        refreshes the audited aisle's `last_audit_closed_at` to the same instant."
        PRD 3.5: "Audits may be listed filtered by `store_id`, `aisle_id`,
        `auditor_associate_id`, `status`, `outcome` and `audit_type`."

        Design: Difficulty/resource_temporal_overlap/aisle_audit_windows_half_open_plus_sixty_minute_cooldown
        """
        jurisdiction_id = build.jurisdiction(
            code="US-CA", scanner_error_rate_threshold_pct=60.0
        )
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        auditor_id = build.certified(
            store_id,
            ROLE_CODE_PRICE_AUDITOR,
            module_code="AUDIT_101",
            employee_number="E-PA1",
            full_name="Pat Auditor",
        )
        aisle_id = build.aisle(store_id, aisle_code="A01", category_code="DAIRY")
        auditor_headers = build.auditor(auditor_id)

        incumbent = build.scanner_audit(
            store_id,
            aisle_id,
            auditor_id,
            scan_window_start="2026-08-01T08:00:00Z",
            scan_window_end="2026-08-01T10:00:00Z",
            actor_headers=auditor_headers,
        )
        assert incumbent["status"] == "OPEN"
        assert incumbent["outcome"] == "PENDING"
        assert incumbent["sample_size"] == 0
        assert incumbent["reopen_count"] == 0
        assert incumbent["closed_at"] is None
        assert incumbent["error_rate_pct"] is None
        assert incumbent["rate_variant_applied"] is None

        validate_error(
            _audit_window(
                api,
                store_id,
                aisle_id,
                auditor_id,
                auditor_headers,
                "2026-08-01T10:30:00Z",
                "2026-08-01T12:00:00Z",
            ),
            ERR_AISLE_AUDIT_WINDOW_CONFLICT,
            409,
        )
        validate_error(
            _audit_window(
                api,
                store_id,
                aisle_id,
                auditor_id,
                auditor_headers,
                "2026-08-01T10:00:00Z",
                "2026-08-01T10:59:00Z",
            ),
            ERR_AISLE_AUDIT_WINDOW_CONFLICT,
            409,
        )
        after_refusals, meta = validate_paginated(
            api.list_scanner_audits(admin_headers, {"aisle_id": aisle_id})
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in after_refusals] == [incumbent["id"]]

        on_the_cooldown_edge = validate_success(
            _audit_window(
                api,
                store_id,
                aisle_id,
                auditor_id,
                auditor_headers,
                "2026-08-01T11:00:00Z",
                "2026-08-01T12:00:00Z",
            ),
            201,
        )
        assert on_the_cooldown_edge["status"] == "OPEN"
        assert on_the_cooldown_edge["sample_size"] == 0

        build.scan_line(incumbent["id"], "00000000022001", 449, 449, auditor_headers)
        scanning = build.read_audit(incumbent["id"])
        assert scanning["status"] == "SCANNING"
        closed = build.close_audit(incumbent["id"], auditor_headers, "GROSS_MISMATCH")
        assert closed["status"] == "CLOSED"
        assert closed["outcome"] == "PASS"
        assert closed["gross_error_rate_pct"] == 0.00
        assert_instant_is(closed["closed_at"], "2026-08-01T00:00:00Z")
        walked_aisle = build.read_aisle(aisle_id)
        assert_instant_is(walked_aisle["last_audit_closed_at"], "2026-08-01T00:00:00Z")

        released = validate_success(
            _audit_window(
                api,
                store_id,
                aisle_id,
                auditor_id,
                auditor_headers,
                "2026-08-01T10:30:00Z",
                "2026-08-01T11:00:00Z",
            ),
            201,
        )
        assert released["status"] == "OPEN"
        assert released["aisle_id"] == aisle_id

        rows, final_meta = validate_paginated(
            api.list_scanner_audits(admin_headers, {"aisle_id": aisle_id})
        )
        assert final_meta["total_count"] == 3
        assert {row["id"] for row in rows} == {
            incumbent["id"],
            on_the_cooldown_edge["id"],
            released["id"],
        }

    def test_the_breather_hangs_off_the_end_only_and_a_reopened_walk_takes_its_aisle_back(
        self, api, build, admin_headers, officer_headers
    ):
        """Touching an incumbent from below is legal; a withdrawn verdict re-reserves the aisle.

        PRD 2.9: "A conflict exists when the new window's start is earlier than an
        existing window's end plus 60 minutes **and** that existing window's start is
        earlier than the new window's end, considering only audits on the same aisle
        that are not `CLOSED`."
        PRD 3.5: "Each existing window on the same aisle is therefore extended by a
        60-minute cooldown after its end, and a new window conflicts when its start
        falls before that extended end **while** the existing window's start falls
        before the new window's end — considering only audits on that aisle which are
        not yet `CLOSED`."
        PRD 3.5: "Closing moves the audit `SCANNING → CLOSED` or `REOPENED → CLOSED`
        — the two source states behave identically — and it is what stamps the
        verdict."
        PRD 3.5: "On success the verdict is withdrawn: `outcome` returns to `PENDING`,
        and `error_rate_pct`, `rate_variant_applied`, `gross_error_rate_pct`,
        `net_overcharge_rate_pct` and `closed_at` all return to null."
        PRD 3.5: "`reopen_count` rises by one."

        Design: Difficulty/resource_temporal_overlap/aisle_audit_windows_half_open_plus_sixty_minute_cooldown
        """
        jurisdiction_id = build.jurisdiction(
            code="US-CA", scanner_error_rate_threshold_pct=60.0
        )
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        auditor_id = build.certified(
            store_id,
            ROLE_CODE_PRICE_AUDITOR,
            module_code="AUDIT_101",
            employee_number="E-PA1",
            full_name="Pat Auditor",
        )
        aisle_one = build.aisle(store_id, aisle_code="A01", category_code="DAIRY")
        aisle_two = build.aisle(store_id, aisle_code="A02", category_code="BAKERY")
        auditor_headers = build.auditor(auditor_id)

        incumbent = build.scanner_audit(
            store_id,
            aisle_one,
            auditor_id,
            scan_window_start="2026-08-01T11:00:00Z",
            scan_window_end="2026-08-01T13:00:00Z",
            actor_headers=auditor_headers,
        )
        validate_error(
            _audit_window(
                api,
                store_id,
                aisle_one,
                auditor_id,
                auditor_headers,
                "2026-08-01T09:00:00Z",
                "2026-08-01T11:01:00Z",
            ),
            ERR_AISLE_AUDIT_WINDOW_CONFLICT,
            409,
        )
        touching_from_below = validate_success(
            _audit_window(
                api,
                store_id,
                aisle_one,
                auditor_id,
                auditor_headers,
                "2026-08-01T09:00:00Z",
                "2026-08-01T11:00:00Z",
            ),
            201,
        )
        assert touching_from_below["status"] == "OPEN"
        assert touching_from_below["aisle_id"] == aisle_one

        validate_error(
            _audit_window(
                api,
                store_id,
                aisle_one,
                auditor_id,
                auditor_headers,
                "2026-08-01T12:00:00Z",
                "2026-08-01T12:30:00Z",
            ),
            ERR_AISLE_AUDIT_WINDOW_CONFLICT,
            409,
        )
        build.scan_line(incumbent["id"], "00000000023001", 449, 449, auditor_headers)
        closed_incumbent = build.close_audit(
            incumbent["id"], auditor_headers, "GROSS_MISMATCH"
        )
        assert closed_incumbent["status"] == "CLOSED"
        assert closed_incumbent["outcome"] == "PASS"
        inside_the_released_span = validate_success(
            _audit_window(
                api,
                store_id,
                aisle_one,
                auditor_id,
                auditor_headers,
                "2026-08-01T12:00:00Z",
                "2026-08-01T12:30:00Z",
            ),
            201,
        )
        assert inside_the_released_span["status"] == "OPEN"

        aisle_one_rows, aisle_one_meta = validate_paginated(
            api.list_scanner_audits(admin_headers, {"aisle_id": aisle_one})
        )
        assert aisle_one_meta["total_count"] == 3
        assert {row["id"] for row in aisle_one_rows} == {
            incumbent["id"],
            touching_from_below["id"],
            inside_the_released_span["id"],
        }

        evidence = build.scanner_audit(
            store_id,
            aisle_two,
            auditor_id,
            scan_window_start="2026-08-01T08:00:00Z",
            scan_window_end="2026-08-01T10:00:00Z",
            actor_headers=auditor_headers,
        )
        build.scan_line(evidence["id"], "00000000023002", 259, 259, auditor_headers)
        first_close = build.close_audit(evidence["id"], auditor_headers, "GROSS_MISMATCH")
        assert first_close["status"] == "CLOSED"
        assert first_close["outcome"] == "PASS"
        neighbour = validate_success(
            _audit_window(
                api,
                store_id,
                aisle_two,
                auditor_id,
                auditor_headers,
                "2026-08-01T10:30:00Z",
                "2026-08-01T11:00:00Z",
            ),
            201,
        )
        assert neighbour["status"] == "OPEN"

        reopened = build.reopen_audit(
            evidence["id"], "Register export was incomplete", officer_headers
        )
        assert reopened["status"] == "REOPENED"
        assert reopened["outcome"] == "PENDING"
        assert reopened["reopen_count"] == 1
        assert reopened["closed_at"] is None
        assert reopened["error_rate_pct"] is None
        assert reopened["gross_error_rate_pct"] is None
        assert reopened["net_overcharge_rate_pct"] is None
        assert reopened["rate_variant_applied"] is None

        validate_error(
            _audit_window(
                api,
                store_id,
                aisle_two,
                auditor_id,
                auditor_headers,
                "2026-08-01T10:00:00Z",
                "2026-08-01T10:30:00Z",
            ),
            ERR_AISLE_AUDIT_WINDOW_CONFLICT,
            409,
        )
        second_close = build.close_audit(evidence["id"], auditor_headers, "GROSS_MISMATCH")
        assert second_close["status"] == "CLOSED"
        assert second_close["outcome"] == "PASS"
        assert second_close["reopen_count"] == 1
        accepted_after_reclose = validate_success(
            _audit_window(
                api,
                store_id,
                aisle_two,
                auditor_id,
                auditor_headers,
                "2026-08-01T10:00:00Z",
                "2026-08-01T10:30:00Z",
            ),
            201,
        )
        assert accepted_after_reclose["status"] == "OPEN"

        aisle_two_rows, aisle_two_meta = validate_paginated(
            api.list_scanner_audits(admin_headers, {"aisle_id": aisle_two})
        )
        assert aisle_two_meta["total_count"] == 3
        assert {row["id"] for row in aisle_two_rows} == {
            evidence["id"],
            neighbour["id"],
            accepted_after_reclose["id"],
        }


FOUR_DAIRY_LINES = [
    {"item_upc": "00000000024001", "item_description": "Milk 1gal", "category_code": "DAIRY",
     "old_retail_cents": 449, "new_retail_cents": 399, "net_content_qty": 1, "net_content_uom": "GAL"},
    {"item_upc": "00000000024002", "item_description": "Butter 1lb", "category_code": "DAIRY",
     "old_retail_cents": 599, "new_retail_cents": 549, "net_content_qty": 1, "net_content_uom": "LB"},
    {"item_upc": "00000000024003", "item_description": "Yogurt 32oz", "category_code": "DAIRY",
     "old_retail_cents": 399, "new_retail_cents": 349, "net_content_qty": 32, "net_content_uom": "OZ"},
    {"item_upc": "00000000024004", "item_description": "Cheese 8oz", "category_code": "DAIRY",
     "old_retail_cents": 499, "new_retail_cents": 459, "net_content_qty": 8, "net_content_uom": "OZ"},
]


class TestAssociateLabourTouching:
    def test_a_window_that_merely_touches_is_refused_while_the_same_window_is_free_for_a_colleague(
        self, api, build, admin_headers
    ):
        """Closed-closed on one assignee: the touching minute is taken, the next minute is not.

        PRD 2.9: "A conflict exists when the new start is at or before an existing end
        **and** that existing start is at or before the new end."
        PRD 3.4: "Labour intervals for one assignee may not touch or overlap: because
        the comparison uses closed-closed semantics, a new interval that begins at the
        exact instant an existing non-terminal task of the same assignee ends is
        already a conflict, refused with `ERR_ASSOCIATE_SCHEDULE_CONFLICT`."
        PRD 3.4: "A newly created task begins with its print axis at `NOT_PRINTED`, its
        placement axis at `UNPLACED`, `printed_label_serial`,
        `placed_by_associate_id`, `verified_by_associate_id`, `placed_at`,
        `verified_at` and `observed_shelf_price_cents` all null, and `rejection_count`
        at 0."
        PRD 3.4: "The **placement axis** takes `UNPLACED`, `PLACED`, `VERIFIED` and
        `REJECTED`, and `VERIFIED` is its terminal value."
        PRD 3.4: "Label tasks are discoverable through a single filtered list that
        collapses all six of the task's associate- and resource-valued references into
        query parameters: `store_id`, `price_change_line_id`, `aisle_id`,
        `assigned_associate_id`, `placed_by_associate_id` and
        `verified_by_associate_id`, plus `print_status`, `placement_status` and
        `overdue`."

        Design: Difficulty/resource_temporal_overlap/associate_label_task_windows_closed_closed_so_touching_conflicts
        """
        jurisdiction_id = build.jurisdiction(code="US-CA", grace_period_hours=48)
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        la1 = build.certified(
            store_id,
            ROLE_CODE_LABEL_ASSOCIATE,
            employee_number="E-LA1",
            full_name="Lena Label",
        )
        la2 = build.certified(
            store_id,
            ROLE_CODE_LABEL_ASSOCIATE,
            employee_number="E-LA2",
            full_name="Leo Label",
        )
        pa1 = build.certified(
            store_id,
            ROLE_CODE_PRICE_AUDITOR,
            module_code="AUDIT_101",
            employee_number="E-PA1",
            full_name="Pat Auditor",
        )
        aisle_id = build.aisle(store_id, aisle_code="A01", category_code="DAIRY")
        built = build.distributed_file(
            jurisdiction_id,
            [store_id],
            FOUR_DAIRY_LINES,
            effective_date="2026-08-03T00:00:00Z",
            file_number="PCF-1001",
        )
        lines = built["line_ids"]

        incumbent = build.label_task(
            built["file_id"],
            store_id,
            lines[0],
            aisle_id,
            la1,
            scheduled_start_at="2026-08-03T09:00:00Z",
            scheduled_end_at="2026-08-03T10:00:00Z",
        )
        assert incumbent["print_status"] == "NOT_PRINTED"
        assert incumbent["placement_status"] == "UNPLACED"
        assert incumbent["printed_label_serial"] is None
        assert incumbent["placed_by_associate_id"] is None
        assert incumbent["verified_by_associate_id"] is None
        assert incumbent["placed_at"] is None
        assert incumbent["verified_at"] is None
        assert incumbent["observed_shelf_price_cents"] is None
        assert incumbent["rejection_count"] == 0
        assert_instant_is(incumbent["due_at"], "2026-08-05T00:00:00Z")
        assert incumbent["overdue"] is False

        validate_error(
            _task_attempt(
                api,
                build,
                built["file_id"],
                store_id,
                lines[1],
                aisle_id,
                la1,
                "2026-08-03T10:00:00Z",
                "2026-08-03T11:00:00Z",
            ),
            ERR_ASSOCIATE_SCHEDULE_CONFLICT,
            409,
        )
        colleague = validate_success(
            _task_attempt(
                api,
                build,
                built["file_id"],
                store_id,
                lines[1],
                aisle_id,
                la2,
                "2026-08-03T10:00:00Z",
                "2026-08-03T11:00:00Z",
            ),
            201,
        )
        assert colleague["assigned_associate_id"] == la2
        assert colleague["print_status"] == "NOT_PRINTED"
        assert colleague["placement_status"] == "UNPLACED"

        one_minute_later = validate_success(
            _task_attempt(
                api,
                build,
                built["file_id"],
                store_id,
                lines[2],
                aisle_id,
                la1,
                "2026-08-03T10:01:00Z",
                "2026-08-03T11:00:00Z",
            ),
            201,
        )
        assert one_minute_later["assigned_associate_id"] == la1

        la1_headers = build.associate_headers(la1)
        build.print_task(incumbent["id"], la1_headers)
        build.place_task(incumbent["id"], 399, la1_headers)
        verified = build.verify_task(incumbent["id"], build.auditor(pa1))
        assert verified["placement_status"] == "VERIFIED"

        inside_the_terminal_window = validate_success(
            _task_attempt(
                api,
                build,
                built["file_id"],
                store_id,
                lines[3],
                aisle_id,
                la1,
                "2026-08-03T09:30:00Z",
                "2026-08-03T09:45:00Z",
            ),
            201,
        )
        assert inside_the_terminal_window["assigned_associate_id"] == la1
        assert inside_the_terminal_window["placement_status"] == "UNPLACED"

        la1_rows, la1_meta = validate_paginated(
            api.list_label_tasks(admin_headers, {"assigned_associate_id": la1})
        )
        assert la1_meta["total_count"] == 3
        assert {row["id"] for row in la1_rows} == {
            incumbent["id"],
            one_minute_later["id"],
            inside_the_terminal_window["id"],
        }
        la2_rows, la2_meta = validate_paginated(
            api.list_label_tasks(admin_headers, {"assigned_associate_id": la2})
        )
        assert la2_meta["total_count"] == 1
        assert [row["id"] for row in la2_rows] == [colleague["id"]]

    def test_the_reservation_follows_the_assignee_across_files_until_the_task_turns_terminal(
        self, api, build, admin_headers
    ):
        """Enclosed, enclosing, touching from below and living in another batch are all one clash.

        PRD 2.9: "Labour intervals for one assignee must not overlap, with
        closed-closed semantics: a new interval that merely touches an existing
        non-terminal label task window of the same assignee is a conflict."
        PRD 3.4: "Two scheduling rules apply to the assignee rather than to the task."
        PRD 3.4: "Labour intervals for one assignee may not touch or overlap: because
        the comparison uses closed-closed semantics, a new interval that begins at the
        exact instant an existing non-terminal task of the same assignee ends is
        already a conflict, refused with `ERR_ASSOCIATE_SCHEDULE_CONFLICT`."
        PRD 3.4: "The **placement axis** takes `UNPLACED`, `PLACED`, `VERIFIED` and
        `REJECTED`, and `VERIFIED` is its terminal value."
        PRD 3.4: "Label tasks are discoverable through a single filtered list that
        collapses all six of the task's associate- and resource-valued references into
        query parameters: `store_id`, `price_change_line_id`, `aisle_id`,
        `assigned_associate_id`, `placed_by_associate_id` and
        `verified_by_associate_id`, plus `print_status`, `placement_status` and
        `overdue`."

        Design: Difficulty/resource_temporal_overlap/associate_label_task_windows_closed_closed_so_touching_conflicts
        """
        jurisdiction_id = build.jurisdiction(code="US-CA", grace_period_hours=48)
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
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
        aisle_id = build.aisle(store_id, aisle_code="A01", category_code="DAIRY")
        first = build.distributed_file(
            jurisdiction_id,
            [store_id],
            FOUR_DAIRY_LINES,
            effective_date="2026-08-03T00:00:00Z",
            file_number="PCF-1001",
        )
        second = build.distributed_file(
            jurisdiction_id,
            [store_id],
            [
                {
                    "item_upc": "00000000024005",
                    "item_description": "Cream 1pt",
                    "category_code": "DAIRY",
                    "old_retail_cents": 329,
                    "new_retail_cents": 299,
                    "net_content_qty": 16,
                    "net_content_uom": "FL_OZ",
                }
            ],
            effective_date="2026-08-03T00:00:00Z",
            file_number="PCF-1002",
        )
        lines = first["line_ids"]

        incumbent = build.label_task(
            first["file_id"],
            store_id,
            lines[0],
            aisle_id,
            la1,
            scheduled_start_at="2026-08-03T09:00:00Z",
            scheduled_end_at="2026-08-03T10:00:00Z",
        )
        assert incumbent["placement_status"] == "UNPLACED"

        for start, end in (
            ("2026-08-03T08:00:00Z", "2026-08-03T09:00:00Z"),
            ("2026-08-03T09:15:00Z", "2026-08-03T09:45:00Z"),
            ("2026-08-03T08:00:00Z", "2026-08-03T11:00:00Z"),
        ):
            validate_error(
                _task_attempt(
                    api,
                    build,
                    first["file_id"],
                    store_id,
                    lines[1],
                    aisle_id,
                    la1,
                    start,
                    end,
                ),
                ERR_ASSOCIATE_SCHEDULE_CONFLICT,
                409,
            )

        just_before = validate_success(
            _task_attempt(
                api,
                build,
                first["file_id"],
                store_id,
                lines[1],
                aisle_id,
                la1,
                "2026-08-03T07:00:00Z",
                "2026-08-03T08:59:00Z",
            ),
            201,
        )
        assert just_before["assigned_associate_id"] == la1

        validate_error(
            _task_attempt(
                api,
                build,
                second["file_id"],
                store_id,
                second["line_ids"][0],
                aisle_id,
                la1,
                "2026-08-03T09:30:00Z",
                "2026-08-03T10:30:00Z",
            ),
            ERR_ASSOCIATE_SCHEDULE_CONFLICT,
            409,
        )
        other_batch = validate_success(
            _task_attempt(
                api,
                build,
                second["file_id"],
                store_id,
                second["line_ids"][0],
                aisle_id,
                la1,
                "2026-08-03T11:00:00Z",
                "2026-08-03T12:00:00Z",
            ),
            201,
        )
        assert other_batch["price_change_line_id"] == second["line_ids"][0]
        assert other_batch["assigned_associate_id"] == la1

        la1_headers = build.associate_headers(la1)
        build.print_task(incumbent["id"], la1_headers)
        build.place_task(incumbent["id"], 399, la1_headers)
        verified = build.verify_task(incumbent["id"], build.auditor(pa1))
        assert verified["placement_status"] == "VERIFIED"
        assert verified["verified_by_associate_id"] == pa1

        released = validate_success(
            _task_attempt(
                api,
                build,
                first["file_id"],
                store_id,
                lines[2],
                aisle_id,
                la1,
                "2026-08-03T09:15:00Z",
                "2026-08-03T09:45:00Z",
            ),
            201,
        )
        assert released["placement_status"] == "UNPLACED"
        assert released["print_status"] == "NOT_PRINTED"

        rows, meta = validate_paginated(
            api.list_label_tasks(admin_headers, {"assigned_associate_id": la1})
        )
        assert meta["total_count"] == 4
        assert {row["id"] for row in rows} == {
            incumbent["id"],
            just_before["id"],
            other_batch["id"],
            released["id"],
        }


class TestAssociateDailyMinuteCap:
    def test_the_four_hundred_and_eightieth_minute_is_fine_and_the_next_day_starts_over(
        self, api, build, admin_headers
    ):
        """An aggregate, not an overlap: disjoint windows still add up, and the calendar day resets them.

        PRD 2.9: "The total scheduled minutes for one assignee on a single UTC calendar
        day may not exceed 480 minutes — eight hours — counting the new task plus all
        existing non-terminal tasks."
        PRD 3.4: "Separately, one assignee's total scheduled minutes on a single UTC
        calendar day — counting the new task together with all their existing
        non-terminal tasks — may not exceed eight hours; the four-hundred-and-eightieth
        minute is fine, the four-hundred-and-eighty-first is not, and the refusal is
        `ERR_ASSOCIATE_DAILY_CAP_EXCEEDED`."
        PRD 3.4: "`due_at` is the effective date of the batch that owns the line,
        advanced by the jurisdiction's grace period in hours — with the default grace
        period that is two days after the price becomes binding."
        PRD 3.4: "`overdue` is true when the current instant is at or after `due_at`
        **and** the placement axis reads either `UNPLACED` or `REJECTED`; it is
        re-derived on every read of the task and on every placement-axis transition,
        and instants are compared at millisecond resolution with the boundary counted
        as already overdue rather than still on time."
        PRD 3.4: "Label tasks are discoverable through a single filtered list that
        collapses all six of the task's associate- and resource-valued references into
        query parameters: `store_id`, `price_change_line_id`, `aisle_id`,
        `assigned_associate_id`, `placed_by_associate_id` and
        `verified_by_associate_id`, plus `print_status`, `placement_status` and
        `overdue`."

        Design: Difficulty/resource_temporal_overlap/associate_daily_minute_cap_is_an_aggregate_not_an_overlap
        """
        jurisdiction_id = build.jurisdiction(code="US-CA", grace_period_hours=96)
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        la1 = build.certified(
            store_id,
            ROLE_CODE_LABEL_ASSOCIATE,
            employee_number="E-LA1",
            full_name="Lena Label",
        )
        aisle_id = build.aisle(store_id, aisle_code="A01", category_code="DAIRY")
        built = build.distributed_file(
            jurisdiction_id,
            [store_id],
            FOUR_DAIRY_LINES,
            effective_date="2026-08-03T00:00:00Z",
            file_number="PCF-1001",
        )
        lines = built["line_ids"]

        seven_hours = build.label_task(
            built["file_id"],
            store_id,
            lines[0],
            aisle_id,
            la1,
            scheduled_start_at="2026-08-03T00:00:00Z",
            scheduled_end_at="2026-08-03T07:00:00Z",
        )
        assert seven_hours["assigned_associate_id"] == la1
        assert_instant_is(seven_hours["due_at"], "2026-08-07T00:00:00Z")
        assert seven_hours["overdue"] is False

        exactly_at_the_cap = validate_success(
            _task_attempt(
                api,
                build,
                built["file_id"],
                store_id,
                lines[1],
                aisle_id,
                la1,
                "2026-08-03T07:01:00Z",
                "2026-08-03T08:01:00Z",
            ),
            201,
        )
        assert exactly_at_the_cap["placement_status"] == "UNPLACED"
        assert_instant_is(exactly_at_the_cap["due_at"], "2026-08-07T00:00:00Z")
        assert exactly_at_the_cap["overdue"] is False

        validate_error(
            _task_attempt(
                api,
                build,
                built["file_id"],
                store_id,
                lines[2],
                aisle_id,
                la1,
                "2026-08-03T08:02:00Z",
                "2026-08-03T08:03:00Z",
            ),
            ERR_ASSOCIATE_DAILY_CAP_EXCEEDED,
            422,
        )
        after_refusal, refusal_meta = validate_paginated(
            api.list_label_tasks(admin_headers, {"assigned_associate_id": la1})
        )
        assert refusal_meta["total_count"] == 2
        assert {row["id"] for row in after_refusal} == {
            seven_hours["id"],
            exactly_at_the_cap["id"],
        }

        next_calendar_day = validate_success(
            _task_attempt(
                api,
                build,
                built["file_id"],
                store_id,
                lines[2],
                aisle_id,
                la1,
                "2026-08-04T08:02:00Z",
                "2026-08-04T08:03:00Z",
            ),
            201,
        )
        assert next_calendar_day["assigned_associate_id"] == la1
        assert next_calendar_day["print_status"] == "NOT_PRINTED"
        assert next_calendar_day["placement_status"] == "UNPLACED"
        assert_instant_is(next_calendar_day["due_at"], "2026-08-07T00:00:00Z")
        assert next_calendar_day["overdue"] is False

        rows, meta = validate_paginated(
            api.list_label_tasks(admin_headers, {"assigned_associate_id": la1})
        )
        assert meta["total_count"] == 3
        assert {row["id"] for row in rows} == {
            seven_hours["id"],
            exactly_at_the_cap["id"],
            next_calendar_day["id"],
        }

    def test_the_conflict_speaks_before_the_quota_and_a_verified_task_stops_consuming_the_day(
        self, api, build, admin_headers
    ):
        """The cap sits at the bottom of the ladder and only counts work that is still outstanding.

        PRD 3.4: "As the fiscal-style quota at the very bottom of the ladder, this cap
        is the last thing checked, so a request that is both over cap and
        schedule-conflicting reports the conflict."
        PRD 2.9: "The total scheduled minutes for one assignee on a single UTC calendar
        day may not exceed 480 minutes — eight hours — counting the new task plus all
        existing non-terminal tasks."
        PRD 2.9: "A conflict exists when the new start is at or before an existing end
        **and** that existing start is at or before the new end."
        PRD 3.4: "Separately, one assignee's total scheduled minutes on a single UTC
        calendar day — counting the new task together with all their existing
        non-terminal tasks — may not exceed eight hours; the four-hundred-and-eightieth
        minute is fine, the four-hundred-and-eighty-first is not, and the refusal is
        `ERR_ASSOCIATE_DAILY_CAP_EXCEEDED`."
        PRD 3.4: "The **placement axis** takes `UNPLACED`, `PLACED`, `VERIFIED` and
        `REJECTED`, and `VERIFIED` is its terminal value."

        Design: Difficulty/resource_temporal_overlap/associate_daily_minute_cap_is_an_aggregate_not_an_overlap
        """
        jurisdiction_id = build.jurisdiction(code="US-CA", grace_period_hours=96)
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
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
        aisle_id = build.aisle(store_id, aisle_code="A01", category_code="DAIRY")
        built = build.distributed_file(
            jurisdiction_id,
            [store_id],
            FOUR_DAIRY_LINES,
            effective_date="2026-08-03T00:00:00Z",
            file_number="PCF-1001",
        )
        spare = build.distributed_file(
            jurisdiction_id,
            [store_id],
            [
                {
                    "item_upc": "00000000024006",
                    "item_description": "Kefir 1qt",
                    "category_code": "DAIRY",
                    "old_retail_cents": 429,
                    "new_retail_cents": 399,
                    "net_content_qty": 1,
                    "net_content_uom": "EACH",
                }
            ],
            effective_date="2026-08-03T00:00:00Z",
            file_number="PCF-1002",
        )
        lines = built["line_ids"]

        seven_hours = build.label_task(
            built["file_id"],
            store_id,
            lines[0],
            aisle_id,
            la1,
            scheduled_start_at="2026-08-03T00:00:00Z",
            scheduled_end_at="2026-08-03T07:00:00Z",
        )
        assert seven_hours["placement_status"] == "UNPLACED"

        validate_error(
            _task_attempt(
                api,
                build,
                built["file_id"],
                store_id,
                lines[1],
                aisle_id,
                la1,
                "2026-08-03T06:30:00Z",
                "2026-08-03T08:00:00Z",
            ),
            ERR_ASSOCIATE_SCHEDULE_CONFLICT,
            409,
        )
        at_the_cap = validate_success(
            _task_attempt(
                api,
                build,
                built["file_id"],
                store_id,
                lines[1],
                aisle_id,
                la1,
                "2026-08-03T07:01:00Z",
                "2026-08-03T08:01:00Z",
            ),
            201,
        )
        assert at_the_cap["assigned_associate_id"] == la1
        validate_error(
            _task_attempt(
                api,
                build,
                built["file_id"],
                store_id,
                lines[2],
                aisle_id,
                la1,
                "2026-08-03T08:02:00Z",
                "2026-08-03T08:03:00Z",
            ),
            ERR_ASSOCIATE_DAILY_CAP_EXCEEDED,
            422,
        )

        la1_headers = build.associate_headers(la1)
        build.print_task(seven_hours["id"], la1_headers)
        build.place_task(seven_hours["id"], 399, la1_headers)
        verified = build.verify_task(seven_hours["id"], build.auditor(pa1))
        assert verified["placement_status"] == "VERIFIED"
        assert verified["placed_by_associate_id"] == la1

        one_minute = validate_success(
            _task_attempt(
                api,
                build,
                built["file_id"],
                store_id,
                lines[2],
                aisle_id,
                la1,
                "2026-08-03T08:02:00Z",
                "2026-08-03T08:03:00Z",
            ),
            201,
        )
        assert one_minute["placement_status"] == "UNPLACED"
        six_more_hours = validate_success(
            _task_attempt(
                api,
                build,
                built["file_id"],
                store_id,
                lines[3],
                aisle_id,
                la1,
                "2026-08-03T09:00:00Z",
                "2026-08-03T15:00:00Z",
            ),
            201,
        )
        assert six_more_hours["assigned_associate_id"] == la1

        validate_error(
            _task_attempt(
                api,
                build,
                spare["file_id"],
                store_id,
                spare["line_ids"][0],
                aisle_id,
                la1,
                "2026-08-03T16:00:00Z",
                "2026-08-03T17:00:00Z",
            ),
            ERR_ASSOCIATE_DAILY_CAP_EXCEEDED,
            422,
        )
        back_at_the_cap = validate_success(
            _task_attempt(
                api,
                build,
                spare["file_id"],
                store_id,
                spare["line_ids"][0],
                aisle_id,
                la1,
                "2026-08-03T16:00:00Z",
                "2026-08-03T16:59:00Z",
            ),
            201,
        )
        assert back_at_the_cap["placement_status"] == "UNPLACED"

        rows, meta = validate_paginated(
            api.list_label_tasks(admin_headers, {"assigned_associate_id": la1})
        )
        assert meta["total_count"] == 5
        assert {row["id"] for row in rows} == {
            seven_hours["id"],
            at_the_cap["id"],
            one_minute["id"],
            six_more_hours["id"],
            back_at_the_cap["id"],
        }
