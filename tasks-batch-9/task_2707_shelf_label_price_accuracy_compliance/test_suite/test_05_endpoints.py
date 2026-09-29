"""Endpoint surface behaviour: partial update, action endpoints, bulk issuance and computed reads."""

from test_helpers import (
    assert_instant_is,
    assert_label_serial,
    assert_money_cents,
    assert_pct,
    assert_posture,
    expected_penalty_exposure_cents,
    factories,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_ASSOCIATE_STORE_MISMATCH,
    ERR_FINDINGS_EMPTY,
    ERR_INVALID_REQUEST,
    ERR_LABEL_NOT_PRINTED,
    ERR_MISSING_DISCLOSURE,
)
from test_helpers.constants import (
    POSTURE_OPEN,
    POSTURE_RESTRICTED,
    ROLE_CODE_LABEL_ASSOCIATE,
    ROLE_CODE_PRICE_AUDITOR,
    ROLE_CODE_STORE_MANAGER,
)


class TestPartialJurisdictionUpdate:
    def test_the_patch_touches_only_the_fields_it_names_and_bumps_the_version_once(
        self, api, build, admin_headers, officer_headers
    ):
        """Two amended tunables leave every other rulebook value byte-identical.

        PRD 3.1: "Amendments are where a jurisdiction becomes interesting. Every
        rulebook setting except `code` and `name` may be amended after the fact,
        and an amendment takes effect immediately for evaluations that read the
        rulebook at evaluation time."
        PRD 3.1: "Jurisdictions may be listed and filtered by `code`."

        Design: Corner/Endpoints/corner_patch_jurisdiction_is_a_partial_update_of_the_amendable_tunables_only
        """
        created = build.jurisdiction_record(
            code="US-CA",
            name="California",
            unit_price_required=True,
            unit_price_decimal_places=3,
            refund_cap_cents=5000,
            grace_period_hours=48,
        )
        assert_pct(created["scanner_error_rate_threshold_pct"], 2.0)
        assert created["overcharge_refund_policy"] == "REFUND_DIFFERENCE_ONLY"
        assert created["unit_price_decimal_places"] == 3

        amended = validate_success(
            api.amend_jurisdiction(
                created["id"],
                {"scanner_error_rate_threshold_pct": 3.5, "refund_cap_cents": 2500},
                admin_headers,
            )
        )
        assert amended["version"] == created["version"] + 1
        assert_pct(amended["scanner_error_rate_threshold_pct"], 3.5)
        assert_money_cents(amended["refund_cap_cents"], 2500)
        assert amended["code"] == "US-CA"
        assert amended["name"] == "California"
        assert amended["unit_price_required"] is True
        assert amended["unit_price_decimal_places"] == 3
        assert amended["overcharge_refund_policy"] == "REFUND_DIFFERENCE_ONLY"
        assert amended["grace_period_hours"] == 48

        read_back = validate_success(
            api.get_jurisdiction(created["id"], officer_headers)
        )
        assert read_back["version"] == amended["version"]
        assert_pct(read_back["scanner_error_rate_threshold_pct"], 3.5)
        assert_money_cents(read_back["refund_cap_cents"], 2500)

        rows, meta = validate_paginated(
            api.list_jurisdictions(admin_headers, {"code": "US-CA"})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == created["id"]


class TestPlaceAction:
    def test_placement_is_gated_by_the_print_axis_and_stamps_the_acting_associate(
        self, api, build, admin_headers
    ):
        """The other axis guards this one, and the placer comes from the header.

        PRD 3.4: "Placement requires the print axis to read exactly `PRINTED` — a
        task that was rejected and consequently needs reprinting cannot simply be
        re-placed, and the attempt is refused with `ERR_LABEL_NOT_PRINTED`. The
        acting `X-User-ID` must resolve to an associate belonging to the task's
        own store, otherwise `ERR_ASSOCIATE_STORE_MISMATCH`."
        PRD 2.7: "`label_backlog_count` is the number of this store's label tasks
        whose placement axis is `UNPLACED` or `REJECTED` **and** whose underlying
        price change line is not `WITHDRAWN`."
        PRD 3.4: "On success a `printed_label_serial` is minted as the literal
        prefix `LBL-` followed by a zero-padded print sequence number maintained
        per store, and the same per-store sequence supplies the re-minted serial
        on a reprint. Printing also advances the underlying line `TASKED →
        LABELED` when the line is in `TASKED`. The placement axis is untouched by
        printing."

        Design: Corner/Endpoints/corner_place_action_enforces_the_print_axis_and_stamps_the_placer
        """
        jurisdiction_id = build.jurisdiction(code="US-CA", grace_period_hours=48)
        store_a = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        store_b = build.store(jurisdiction_id, store_number="S002", name="Elm Plaza")
        manager_id = build.certified(
            store_a,
            ROLE_CODE_STORE_MANAGER,
            employee_number="E-SM1",
            full_name="Sam Manager",
        )
        label_a = build.certified(
            store_a,
            ROLE_CODE_LABEL_ASSOCIATE,
            employee_number="E-LA1",
            full_name="Lee Label",
        )
        label_b = build.certified(
            store_b,
            ROLE_CODE_LABEL_ASSOCIATE,
            employee_number="E-LB1",
            full_name="Bo Label",
        )
        aisle_id = build.aisle(
            store_a,
            aisle_code="A01",
            category_code="DAIRY",
            assigned_associate_id=label_a,
        )
        built = build.distributed_file(
            jurisdiction_id,
            [store_a],
            [
                {
                    "item_upc": "00000000014001",
                    "new_retail_cents": 449,
                    "old_retail_cents": 499,
                    "net_content_qty": 1,
                    "net_content_uom": "GAL",
                    "item_description": "Milk 1 GAL",
                    "category_code": "DAIRY",
                }
            ],
            file_number="PCF-1",
        )
        line_id = built["line_ids"][0]
        task = validate_success(
            api.create_label_task(
                built["file_id"],
                factories.label_task_payload(
                    store_a,
                    line_id,
                    aisle_id,
                    label_a,
                    "2026-08-02T08:00:00Z",
                    "2026-08-02T10:00:00Z",
                    built["version"],
                ),
                build.manager(manager_id),
            ),
            201,
        )
        assert task["print_status"] == "NOT_PRINTED"
        assert task["placement_status"] == "UNPLACED"
        assert task["printed_label_serial"] is None

        headers_a = build.associate_headers(label_a)
        headers_b = build.associate_headers(label_b)
        validate_error(
            api.place_label_task(task["id"], factories.place_payload(449), headers_a),
            ERR_LABEL_NOT_PRINTED,
            409,
        )
        before = build.read_store(store_a)
        assert before["label_backlog_count"] == 1
        assert_posture(before, POSTURE_OPEN)

        printed = build.print_task(task["id"], headers_a)
        assert printed["print_status"] == "PRINTED"
        assert_label_serial(printed["printed_label_serial"])
        assert printed["placement_status"] == "UNPLACED"
        assert build.read_line(line_id)["line_status"] == "LABELED"

        validate_error(
            api.place_label_task(task["id"], factories.place_payload(449), headers_b),
            ERR_ASSOCIATE_STORE_MISMATCH,
            422,
        )

        placed = build.place_task(task["id"], 449, headers_a)
        assert placed["placement_status"] == "PLACED"
        assert placed["placed_by_associate_id"] == label_a
        assert_instant_is(placed["placed_at"], "2026-08-01T00:00:00Z")
        assert_money_cents(placed["observed_shelf_price_cents"], 449)
        assert placed["print_status"] == "PRINTED"

        after = build.read_store(store_a)
        assert after["label_backlog_count"] == 0
        assert_posture(after, POSTURE_OPEN)

        _rows, meta = validate_paginated(
            api.list_label_tasks(admin_headers, {"store_id": store_a})
        )
        assert meta["total_count"] == 1


class TestBulkFindingIssuance:
    def test_one_invalid_element_writes_nothing_and_the_batch_is_priced_as_a_whole(
        self, api, build, admin_headers, officer_headers
    ):
        """The findings array is validated as a unit before a single row is written.

        PRD 3.7: "Each element of the supplied `findings` array carries the
        `finding_code` cited — one of `SHELF_TAG_MISMATCH`, `UNIT_PRICE_FORMAT`,
        `SIGNAGE_DISCLOSURE`, `EXPIRED_SIGNAGE` or `SCANNER_ERROR_RATE` — a
        `severity` of `MINOR`, `MAJOR` or `CRITICAL`, an `affected_item_count` of
        at least 1, and an optional `affected_aisle_code`, which is the free-text
        aisle label the regulator wrote down and is deliberately **not** resolved
        against any aisle record. An empty `findings` array is refused with
        `ERR_FINDINGS_EMPTY`"
        PRD 3.7: "Each created finding takes its `regulatory_inspection_id` from
        the path segment of the call that issued it rather than from the body, and
        starts `OPEN` with `penalty_component_cents` at 0 and
        `remediation_action_code`, `remediation_evidence_ref` and `waiver_reason`
        all null."
        PRD 3.7: "The **tier multiplier** is 100 percentage points when the
        considered set holds at most 2 findings, 125 when it holds at most 5, and
        150 beyond that. An **audit aggravator** of 25 percentage points is added
        when the referenced evidence audit's outcome is `FAIL`, and 0 percentage
        points otherwise."
        PRD 3.7: "The scaled total is that raw total multiplied by the tier
        multiplier plus the aggravator, divided by 100, with a single **floor**
        applied to the result — one floor, after the sum, never per finding,
        because per-finding floors would lose up to one cent per finding."
        PRD 2.7: "Otherwise the posture becomes `RESTRICTED` when the open finding
        count is at least 1, **or** when the thirty-day failed-audit count is
        exactly 1, **or** when the label backlog is at least 5, **or** when at
        least one signage violation exists."

        Design: Corner/Endpoints/corner_issue_findings_bulk_action_is_all_or_nothing
        """
        jurisdiction_id = build.jurisdiction(code="US-CA")
        rulebook = build.read_jurisdiction(jurisdiction_id)
        assert_money_cents(rulebook["penalty_per_violation_cents"], 5000)
        assert_money_cents(rulebook["penalty_max_cents"], 2000000)

        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        auditor_id = build.certified(
            store_id,
            ROLE_CODE_PRICE_AUDITOR,
            module_code="AUDIT_101",
            employee_number="E-PA1",
            full_name="Pat Auditor",
        )
        aisle_id = build.aisle(store_id, aisle_code="A01", category_code="DAIRY")
        evidence = build.closed_audit(
            store_id,
            aisle_id,
            auditor_id,
            [
                {
                    "item_upc": "00000000015001",
                    "shelf_price_cents": 100,
                    "register_price_cents": 100,
                }
            ],
            rate_variant="GROSS_MISMATCH",
            audit_type="REGULATORY",
            scan_window_start="2026-08-01T08:00:00Z",
            scan_window_end="2026-08-01T09:00:00Z",
        )
        assert_pct(evidence["audit"]["error_rate_pct"], 0.00)
        assert evidence["audit"]["outcome"] == "PASS"

        inspection = build.inspection(
            store_id,
            evidence["audit_id"],
            inspector_ref="INS-2026-14",
            inspection_date="2026-08-01T10:00:00Z",
        )
        assert inspection["status"] == "SCHEDULED"
        assert inspection["finding_count"] == 0
        assert_money_cents(inspection["penalty_exposure_cents"], 0)

        rejected_batch = [
            factories.finding_input("SHELF_TAG_MISMATCH", "MINOR", 2, "A01"),
            factories.finding_input("UNIT_PRICE_FORMAT", "MAJOR", 4, "A01"),
            factories.finding_input("EXPIRED_SIGNAGE", "SEVERE", 1, "A01"),
        ]
        validate_error(
            api.issue_inspection_findings(
                inspection["id"],
                factories.issue_findings_payload(rejected_batch),
                officer_headers,
            ),
            ERR_INVALID_REQUEST,
            400,
        )
        _empty_rows, empty_meta = validate_paginated(
            api.list_inspection_findings(inspection["id"], officer_headers)
        )
        assert empty_meta["total_count"] == 0
        untouched = build.read_inspection(inspection["id"])
        assert untouched["status"] == "SCHEDULED"
        assert_money_cents(untouched["penalty_exposure_cents"], 0)

        validate_error(
            api.issue_inspection_findings(
                inspection["id"], factories.issue_findings_payload([]), officer_headers
            ),
            ERR_FINDINGS_EMPTY,
            422,
        )

        accepted_batch = [
            factories.finding_input("SHELF_TAG_MISMATCH", "MINOR", 2, "A01"),
            factories.finding_input("UNIT_PRICE_FORMAT", "MAJOR", 4, "A01"),
        ]
        issued = validate_success(
            api.issue_inspection_findings(
                inspection["id"],
                factories.issue_findings_payload(accepted_batch),
                officer_headers,
            )
        )
        assert issued["status"] == "FINDINGS_ISSUED"
        assert issued["finding_count"] == 2
        assert_money_cents(
            issued["penalty_exposure_cents"],
            expected_penalty_exposure_cents(accepted_batch, 5000, 2000000, False),
        )
        assert_money_cents(issued["penalty_exposure_cents"], 70000)

        rows, meta = validate_paginated(
            api.list_inspection_findings(
                inspection["id"], officer_headers, {"status": "OPEN"}
            )
        )
        assert meta["total_count"] == 2
        components = {row["finding_code"]: row for row in rows}
        assert_money_cents(
            components["SHELF_TAG_MISMATCH"]["penalty_component_cents"], 10000
        )
        assert_money_cents(
            components["UNIT_PRICE_FORMAT"]["penalty_component_cents"], 60000
        )
        assert all(row["status"] == "OPEN" for row in rows)

        store = validate_success(api.get_store(store_id, admin_headers))
        assert store["open_finding_count"] == 2
        assert store["failed_audit_count_30d"] == 0
        assert_posture(store, POSTURE_RESTRICTED)


class TestAssignAssociateLink:
    def test_the_link_sets_clears_and_refuses_an_associate_from_another_store(
        self, api, build
    ):
        """One nullable foreign key, validated in both directions and clearable.

        PRD 3.1: "An aisle may optionally name its accountable label-maintenance
        owner as `assigned_associate_id` at creation, and a store manager may
        later set or clear that owner; the assignee must belong to the aisle's own
        store, which is where `ERR_ASSOCIATE_STORE_MISMATCH` is raised."
        PRD 3.1: "Aisles may be listed by store and filtered by `category_code`,
        and may also be listed by the associate they are assigned to."

        Design: Corner/Endpoints/corner_assign_associate_link_is_validated_in_both_directions_and_clearable
        """
        jurisdiction_id = build.jurisdiction(code="US-CA")
        store_a = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        store_b = build.store(jurisdiction_id, store_number="S002", name="Elm Plaza")
        manager_id = build.certified(
            store_a,
            ROLE_CODE_STORE_MANAGER,
            employee_number="E-SM1",
            full_name="Sam Manager",
        )
        label_a = build.associate(
            store_a,
            ROLE_CODE_LABEL_ASSOCIATE,
            employee_number="E-LA1",
            full_name="Lee Label",
        )
        label_b = build.associate(
            store_b,
            ROLE_CODE_LABEL_ASSOCIATE,
            employee_number="E-LB1",
            full_name="Bo Label",
        )
        manager_headers = build.manager(manager_id)
        aisle_record = validate_success(
            api.create_aisle(
                store_a,
                factories.aisle_payload("A01", "DAIRY"),
                build.admin,
            ),
            201,
        )
        assert aisle_record["assigned_associate_id"] is None
        aisle_id = aisle_record["id"]

        linked = validate_success(
            api.assign_aisle_associate(
                aisle_id,
                factories.assign_associate_payload(label_a),
                manager_headers,
            )
        )
        assert linked["assigned_associate_id"] == label_a

        rows, meta = validate_paginated(
            api.list_associate_aisles(label_a, manager_headers)
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == aisle_id

        validate_error(
            api.assign_aisle_associate(
                aisle_id,
                factories.assign_associate_payload(label_b),
                manager_headers,
            ),
            ERR_ASSOCIATE_STORE_MISMATCH,
            422,
        )
        unchanged = validate_success(api.get_aisle(aisle_id, manager_headers))
        assert unchanged["assigned_associate_id"] == label_a
        assert unchanged["version"] == linked["version"]

        cleared = validate_success(
            api.assign_aisle_associate(
                aisle_id, factories.assign_associate_payload(None), manager_headers
            )
        )
        assert cleared["assigned_associate_id"] is None

        _rows, empty_meta = validate_paginated(
            api.list_associate_aisles(label_a, manager_headers)
        )
        assert empty_meta["total_count"] == 0


class TestComplianceSummaryComputedRead:
    def test_the_recomputing_read_agrees_with_the_plain_read_before_and_after_a_placement(
        self, api, build, admin_headers
    ):
        """The reconciliation read recomputes, so it must never disagree with the stored projection.

        PRD 2.7: "A dedicated read capability exists specifically so that a client
        can reconcile every derived counter against the underlying rows: it
        recomputes the label backlog and the posture from live data before
        returning the store projection, and is therefore the authoritative way to
        observe posture drift after a sequence of cascades."
        PRD 2.7: "`label_backlog_count` is the number of this store's label tasks
        whose placement axis is `UNPLACED` or `REJECTED` **and** whose underlying
        price change line is not `WITHDRAWN`."
        PRD 2.7: "`executed_file_count` is the number of price change files that
        reached the executed state with this store in their scope."
        PRD 3.4: "Label tasks are discoverable through a single filtered list that
        collapses all six of the task's associate- and resource-valued references
        into query parameters: `store_id`, `price_change_line_id`, `aisle_id`,
        `assigned_associate_id`, `placed_by_associate_id` and
        `verified_by_associate_id`, plus `print_status`, `placement_status` and
        `overdue`."

        Design: Corner/Endpoints/corner_compliance_summary_computed_read_matches_the_plain_read
        """
        jurisdiction_id = build.jurisdiction(code="US-CA")
        store_a = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        manager_id = build.certified(
            store_a,
            ROLE_CODE_STORE_MANAGER,
            employee_number="E-SM1",
            full_name="Sam Manager",
        )
        label_a = build.certified(
            store_a,
            ROLE_CODE_LABEL_ASSOCIATE,
            employee_number="E-LA1",
            full_name="Lee Label",
        )
        aisle_id = build.aisle(
            store_a,
            aisle_code="A01",
            category_code="DAIRY",
            assigned_associate_id=label_a,
        )
        manager_headers = build.manager(manager_id)
        built = build.distributed_file(
            jurisdiction_id,
            [store_a],
            [
                {
                    "item_upc": "00000000016001",
                    "new_retail_cents": 449,
                    "old_retail_cents": 499,
                    "net_content_qty": 1,
                    "net_content_uom": "GAL",
                    "item_description": "Milk 1 GAL",
                    "category_code": "DAIRY",
                },
                {
                    "item_upc": "00000000016002",
                    "new_retail_cents": 549,
                    "old_retail_cents": 599,
                    "net_content_qty": 8,
                    "net_content_uom": "OZ",
                    "item_description": "Cheese 8 OZ",
                    "category_code": "DAIRY",
                },
            ],
            file_number="PCF-1",
        )
        first_task = validate_success(
            api.create_label_task(
                built["file_id"],
                factories.label_task_payload(
                    store_a,
                    built["line_ids"][0],
                    aisle_id,
                    label_a,
                    "2026-08-02T08:00:00Z",
                    "2026-08-02T10:00:00Z",
                    built["version"],
                ),
                manager_headers,
            ),
            201,
        )
        second_task = validate_success(
            api.create_label_task(
                built["file_id"],
                factories.label_task_payload(
                    store_a,
                    built["line_ids"][1],
                    aisle_id,
                    label_a,
                    "2026-08-02T12:00:00Z",
                    "2026-08-02T14:00:00Z",
                    build.file_version(built["file_id"]),
                ),
                manager_headers,
            ),
            201,
        )

        plain_before = build.read_store(store_a)
        summary_before = build.read_summary(store_a)
        assert plain_before["label_backlog_count"] == 2
        assert summary_before["label_backlog_count"] == 2
        assert_posture(plain_before, POSTURE_OPEN)
        assert_posture(summary_before, POSTURE_OPEN)
        assert summary_before["executed_file_count"] == 0

        associate_headers = build.associate_headers(label_a)
        build.print_task(first_task["id"], associate_headers)
        placed = build.place_task(first_task["id"], 449, associate_headers)
        assert placed["placement_status"] == "PLACED"

        plain_after = build.read_store(store_a)
        summary_after = build.read_summary(store_a)
        assert plain_after["label_backlog_count"] == 1
        assert summary_after["label_backlog_count"] == 1
        assert_posture(plain_after, POSTURE_OPEN)
        assert_posture(summary_after, POSTURE_OPEN)

        rows, meta = validate_paginated(
            api.list_label_tasks(
                admin_headers, {"store_id": store_a, "placement_status": "UNPLACED"}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == second_task["id"]


class TestSignagePostDisclosureGate:
    def test_the_post_waits_for_the_full_jurisdiction_disclosure_set(self, api, build):
        """One sign short of the required set stays on the desk; the complete sign goes up.

        PRD 3.6: "`missing_disclosure_codes` is the set difference between the
        jurisdiction's `signage_disclosure_codes` and the sign's own
        `disclosure_codes`, compared by exact string equality and **ordered as the
        jurisdiction declares them** rather than sorted"
        PRD 3.6: "A newly drafted sign therefore reads `DRAFT` with
        `compliance_state` `NOT_APPLICABLE`, `posted_at` and `removed_at` null."
        PRD 3.6: "Every disclosure the jurisdiction requires must be present,
        meaning `missing_disclosure_codes` must be empty; otherwise the post is
        refused with `ERR_MISSING_DISCLOSURE`."
        PRD 3.6: "On success `posted_at` is stamped with the current instant and
        `compliance_state` becomes `COMPLIANT`."
        PRD 3.6: "Removal stamps `removed_at` with the current instant, resets
        `compliance_state` to `NOT_APPLICABLE`, and recomputes the store's
        `signage_violation_count` and then its posture"

        Design: Corner/Endpoints/corner_signage_post_is_conditional_on_the_jurisdictions_disclosure_set
        """
        jurisdiction_id = build.jurisdiction(
            code="US-CA",
            signage_disclosure_codes=["UNIT_PRICE_SHOWN", "EXPIRY_DATE"],
        )
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        aisle_id = build.aisle(store_id, aisle_code="A01", category_code="DAIRY")
        manager_id = build.certified(
            store_id,
            ROLE_CODE_STORE_MANAGER,
            employee_number="E-SM1",
            full_name="Sam Manager",
        )
        manager_headers = build.manager(manager_id)

        short_sign = build.promo_signage(
            store_id,
            aisle_id,
            ["UNIT_PRICE_SHOWN"],
            sign_code="SG-1",
            promo_start_at="2026-08-01T00:00:00Z",
            promo_end_at="2026-08-10T00:00:00Z",
        )
        assert short_sign["missing_disclosure_codes"] == ["EXPIRY_DATE"]
        assert short_sign["status"] == "DRAFT"
        assert short_sign["compliance_state"] == "NOT_APPLICABLE"
        assert short_sign["posted_at"] is None
        assert short_sign["removed_at"] is None

        validate_error(
            api.post_promo_signage(
                short_sign["id"], manager_headers, factories.post_signage_payload()
            ),
            ERR_MISSING_DISCLOSURE,
            422,
        )
        still_draft = build.read_signage(short_sign["id"])
        assert still_draft["status"] == "DRAFT"
        assert still_draft["posted_at"] is None

        full_sign = build.promo_signage(
            store_id,
            aisle_id,
            ["EXPIRY_DATE", "UNIT_PRICE_SHOWN"],
            sign_code="SG-2",
            promo_start_at="2026-08-01T00:00:00Z",
            promo_end_at="2026-08-10T00:00:00Z",
        )
        assert full_sign["missing_disclosure_codes"] == []
        assert full_sign["compliance_state"] == "NOT_APPLICABLE"

        posted = build.post_signage(full_sign["id"], manager_headers)
        assert posted["status"] == "POSTED"
        assert posted["compliance_state"] == "COMPLIANT"
        assert_instant_is(posted["posted_at"], "2026-08-01T00:00:00Z")

        removed = build.remove_signage(full_sign["id"], manager_headers)
        assert removed["status"] == "REMOVED"
        assert removed["compliance_state"] == "NOT_APPLICABLE"
        assert_instant_is(removed["removed_at"], "2026-08-01T00:00:00Z")

        store = build.read_store(store_id)
        assert store["signage_violation_count"] == 0
        assert_posture(store, POSTURE_OPEN)
