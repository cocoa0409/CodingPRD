"""Resource representations, defaults, schema refusals, listing and not-found codes."""

from test_helpers import (
    NON_EXISTENT_UUID,
    assert_common_fields,
    assert_instant_is,
    assert_money_cents,
    assert_pct,
    assert_scan_line_shape,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_ACCOUNTABILITY_ACTION_NOT_FOUND,
    ERR_AISLE_NOT_FOUND,
    ERR_AISLE_STORE_MISMATCH,
    ERR_ASSOCIATE_NOT_FOUND,
    ERR_ASSOCIATE_STORE_MISMATCH,
    ERR_EXCEPTION_REPORT_NOT_FOUND,
    ERR_INSPECTION_FINDING_NOT_FOUND,
    ERR_INVALID_PAGINATION,
    ERR_INVALID_REQUEST,
    ERR_INVALID_WINDOW,
    ERR_JURISDICTION_NOT_FOUND,
    ERR_LABEL_TASK_NOT_FOUND,
    ERR_PRICE_CHANGE_FILE_NOT_FOUND,
    ERR_PRICE_CHANGE_LINE_NOT_FOUND,
    ERR_PROMO_SIGNAGE_NOT_FOUND,
    ERR_REFUND_CLAIM_NOT_FOUND,
    ERR_REGULATORY_INSPECTION_NOT_FOUND,
    ERR_SCAN_LINE_NOT_FOUND,
    ERR_SCANNER_AUDIT_NOT_FOUND,
    ERR_STORE_NOT_FOUND,
    ERR_STORE_OUT_OF_FILE_SCOPE,
)
from test_helpers.constants import DEFAULT_CLOCK


class TestJurisdictionRepresentation:
    def test_create_jurisdiction_echoes_every_rulebook_setting(self, api, build, officer_headers):
        """A jurisdiction created with the whole rulebook spelled out returns all of it.

        PRD 2.5: "A jurisdiction is identified to operators by its short `code` —
        globally unique, 2 to 16 characters, restricted to uppercase letters,
        digits and hyphens — and carries a human-readable `name`."
        PRD 2.4: "`version` is an integer that starts at 1 on creation".

        Design: Corner/Entities/corner_create_jurisdiction_returns_declared_fields_and_envelope
        """
        payload = {
            "code": "US-CA",
            "name": "California",
            "unit_price_required": True,
            "unit_price_uom_rule": "PER_UNIT_MEASURE_CANONICAL",
            "unit_price_decimal_places": 2,
            "unit_price_rounding": "ROUND_HALF_UP",
            "scanner_error_rate_threshold_pct": 25.0,
            "default_rate_variant": "GROSS_MISMATCH",
            "overcharge_refund_policy": "REFUND_DIFFERENCE_PLUS_FIXED",
            "refund_fixed_bonus_cents": 500,
            "refund_cap_cents": 5000,
            "refund_budget_per_audit_cents": 100000,
            "penalty_per_violation_cents": 5000,
            "penalty_max_cents": 2000000,
            "signage_disclosure_codes": ["UNIT_PRICE", "EXPIRY_DATE"],
            "grace_period_hours": 48,
            "accountability_variant": "OCCURRENCE_WEIGHTED",
        }
        created = validate_success(api.create_jurisdiction(payload, build.admin), 201)

        assert created["code"] == "US-CA"
        assert created["name"] == "California"
        assert created["unit_price_required"] is True
        assert created["unit_price_uom_rule"] == "PER_UNIT_MEASURE_CANONICAL"
        assert created["unit_price_decimal_places"] == 2
        assert created["unit_price_rounding"] == "ROUND_HALF_UP"
        assert_pct(created["scanner_error_rate_threshold_pct"], 25.0)
        assert created["default_rate_variant"] == "GROSS_MISMATCH"
        assert created["overcharge_refund_policy"] == "REFUND_DIFFERENCE_PLUS_FIXED"
        assert_money_cents(created["refund_fixed_bonus_cents"], 500)
        assert_money_cents(created["refund_cap_cents"], 5000)
        assert_money_cents(created["refund_budget_per_audit_cents"], 100000)
        assert_money_cents(created["penalty_per_violation_cents"], 5000)
        assert_money_cents(created["penalty_max_cents"], 2000000)
        assert created["signage_disclosure_codes"] == ["UNIT_PRICE", "EXPIRY_DATE"]
        assert created["grace_period_hours"] == 48
        assert created["accountability_variant"] == "OCCURRENCE_WEIGHTED"

        assert_common_fields(created, expected_version=1)
        assert_instant_is(created["created_at"], DEFAULT_CLOCK)
        assert_instant_is(created["updated_at"], DEFAULT_CLOCK)

        read_back = validate_success(api.get_jurisdiction(created["id"], officer_headers))
        assert read_back == created

    def test_omitted_optional_rulebook_settings_take_their_declared_defaults(self, api, build):
        """Only code and name supplied: every other setting arrives at its default.

        PRD 2.5: "`scanner_error_rate_threshold_pct` is the inclusive failure
        threshold for an audit's error rate; it must be greater than 0, at most
        100, carry at most two decimals, and defaults to 2.0."

        Design: Corner/Entities/corner_default_values_applied_when_optional_jurisdiction_inputs_omitted
        """
        created = validate_success(
            api.create_jurisdiction({"code": "US-MIN", "name": "Bare Minimum State"}, build.admin),
            201,
        )

        assert created["unit_price_required"] is True
        assert created["unit_price_uom_rule"] == "PER_UNIT_MEASURE_CANONICAL"
        assert created["unit_price_decimal_places"] == 2
        assert created["unit_price_rounding"] == "ROUND_HALF_UP"
        assert_pct(created["scanner_error_rate_threshold_pct"], 2.0)
        assert created["default_rate_variant"] == "GROSS_MISMATCH"
        assert created["overcharge_refund_policy"] == "REFUND_DIFFERENCE_ONLY"
        assert_money_cents(created["refund_fixed_bonus_cents"], 0)
        assert_money_cents(created["refund_cap_cents"], 5000)
        assert_money_cents(created["refund_budget_per_audit_cents"], 100000)
        assert_money_cents(created["penalty_per_violation_cents"], 5000)
        assert_money_cents(created["penalty_max_cents"], 2000000)
        assert created["signage_disclosure_codes"] == []
        assert created["grace_period_hours"] == 48
        assert created["accountability_variant"] == "OCCURRENCE_WEIGHTED"

        # The empty default is a real empty requirement set: a sign carrying no
        # disclosures at all is still compliant once posted.
        staff = build.store_with_staff(created["id"])
        sign = build.posted_signage(
            staff["store_id"], staff["aisle_id"], [], staff["manager_id"]
        )
        assert sign["signage"]["missing_disclosure_codes"] == []
        assert sign["signage"]["status"] == "POSTED"
        assert sign["signage"]["compliance_state"] == "COMPLIANT"


class TestSchemaRefusals:
    def test_omitting_a_required_input_field_persists_nothing(self, api, build):
        """A store without jurisdiction_id and a file without scope_store_ids are both refused.

        PRD 3.1: "A store is opened inside a jurisdiction with `store_number`,
        `name` and `jurisdiction_id`."

        Design: Corner/Entities/corner_missing_required_fields_rejected_with_invalid_request
        """
        jurisdiction_id = build.jurisdiction(code="US-CA")

        validate_error(
            api.create_store({"store_number": "S001", "name": "Bay Street"}, build.admin),
            ERR_INVALID_REQUEST,
        )
        validate_error(
            api.create_price_change_file(
                {
                    "file_number": "PCF-1001",
                    "jurisdiction_id": jurisdiction_id,
                    "effective_date": "2026-08-03T00:00:00Z",
                },
                build.admin,
            ),
            ERR_INVALID_REQUEST,
        )

        stores, stores_meta = validate_paginated(api.list_stores(build.admin))
        assert stores == []
        assert stores_meta["total_count"] == 0
        files, files_meta = validate_paginated(api.list_price_change_files(build.admin))
        assert files == []
        assert files_meta["total_count"] == 0

    def test_bad_enum_is_a_schema_failure_while_an_inverted_window_is_semantic(self, api, build):
        """role_code CASHIER is a 400; a scan window that ends before it starts is a 422.

        PRD 3.1: "Associates are hired into a store, again taking their
        `store_id` from the path segment, with an `employee_number` unique within
        the store, a `full_name`, and a `role_code` of `LABEL_ASSOCIATE`,
        `PRICE_AUDITOR` or `STORE_MANAGER`."
        PRD 3.5: "the half-open occupation window as `scan_window_start`
        (inclusive) and `scan_window_end` (exclusive, and strictly after the
        start)".

        Design: Corner/Entities/corner_type_constraints_reject_bad_enum_and_malformed_window
        """
        jurisdiction_id = build.jurisdiction(code="US-CA")
        store_id = build.store(jurisdiction_id)
        aisle_id = build.aisle(store_id)
        auditor_id = build.certified_auditor(store_id)

        validate_error(
            api.create_associate(
                store_id,
                {
                    "employee_number": "E-BAD",
                    "full_name": "Bad Role",
                    "role_code": "CASHIER",
                },
                build.admin,
            ),
            ERR_INVALID_REQUEST,
        )

        auditor_headers = build.auditor(auditor_id)
        inverted = {
            "store_id": store_id,
            "aisle_id": aisle_id,
            "auditor_associate_id": auditor_id,
            "audit_type": "ROUTINE",
            "scan_window_start": "2026-08-01T10:00:00Z",
            "scan_window_end": "2026-08-01T08:00:00Z",
        }
        validate_error(api.create_scanner_audit(inverted, auditor_headers), ERR_INVALID_WINDOW)

        associates, associates_meta = validate_paginated(
            api.list_store_associates(store_id, build.admin)
        )
        assert associates_meta["total_count"] == 1
        assert associates[0]["id"] == auditor_id
        _, audits_meta = validate_paginated(
            api.list_scanner_audits(build.officer, {"store_id": store_id})
        )
        assert audits_meta["total_count"] == 0

        ordered = dict(inverted)
        ordered["scan_window_start"] = "2026-08-01T08:00:00Z"
        ordered["scan_window_end"] = "2026-08-01T10:00:00Z"
        accepted = validate_success(api.create_scanner_audit(ordered, auditor_headers), 201)
        assert accepted["status"] == "OPEN"


class TestComputedFieldsAreServerOwned:
    def test_line_derives_unit_price_and_initial_status_without_client_input(self, api, build):
        """A 12 OZ line at 1000 cents prints 1333 per pound and starts PENDING.

        PRD 3.3: "The computation has exactly one division and exactly one
        rounding, in that order, and the order is normative."
        PRD 3.3: "and a line begins its own lifecycle in `PENDING`."

        Design: Corner/Entities/corner_computed_and_system_fields_ignore_client_supplied_values
        """
        jurisdiction_id = build.jurisdiction(
            code="US-CA",
            unit_price_uom_rule="PER_UNIT_MEASURE_CANONICAL",
            unit_price_decimal_places=2,
            unit_price_rounding="ROUND_HALF_UP",
        )
        store_id = build.store(jurisdiction_id)
        file_record = build.price_change_file(jurisdiction_id, [store_id], priority="ROUTINE")

        line = build.add_line(
            file_record["id"],
            item_upc="00000000002001",
            new_retail_cents=1000,
            old_retail_cents=1199,
            net_content_qty=12,
            net_content_uom="OZ",
            item_description="Cheese 12oz",
        )

        assert float(line["unit_price_basis_qty"]) == 0.75
        assert line["unit_price_basis_uom"] == "LB"
        assert_money_cents(line["unit_price_display_cents"], 1333)
        assert line["line_status"] == "PENDING"
        assert_common_fields(line, expected_version=1)
        assert_instant_is(line["created_at"], DEFAULT_CLOCK)
        assert_instant_is(line["updated_at"], DEFAULT_CLOCK)

        parent = build.read_file(file_record["id"])
        assert parent["line_count"] == 1
        assert parent["verified_line_count"] == 0

        store = build.read_store(store_id)
        assert store["compliance_posture"] == "OPEN"
        assert store["label_backlog_count"] == 0


class TestRetrievalAndListing:
    def test_filtered_listing_reports_the_matching_count_not_the_page_size(self, api, build):
        """Three California stores paginate two then one while New York never appears.

        PRD 2.3: "`limit` defaults to 10, has a minimum of 1 and a maximum of
        100."
        PRD 2.3: "`offset` defaults to 0 and has a minimum of 0."
        PRD 3.1: "Stores may be listed filtered by `jurisdiction_id` or by
        `compliance_posture`, which is the practical way for a compliance officer
        to find every frozen store in a region."

        Design: Corner/Entities/corner_retrieval_and_listing_with_filter_and_pagination_metadata
        """
        california = build.jurisdiction(code="US-CA", name="California")
        new_york = build.jurisdiction(code="US-NY", name="New York")
        store_a = build.store(california, store_number="S001", name="Bay Street")
        store_b = build.store(california, store_number="S002", name="Market Street")
        store_c = build.store(california, store_number="S003", name="Mission Street")
        store_d = build.store(new_york, store_number="S004", name="Broadway")

        single = validate_success(api.get_store(store_b, build.officer))
        assert single["store_number"] == "S002"
        assert single["jurisdiction_id"] == california

        page_one, meta_one = validate_paginated(
            api.list_stores(build.admin, {"jurisdiction_id": california, "limit": 2, "offset": 0})
        )
        assert len(page_one) == 2
        assert meta_one["total_count"] == 3
        assert meta_one["has_more"] is True

        page_two, meta_two = validate_paginated(
            api.list_stores(build.admin, {"jurisdiction_id": california, "limit": 2, "offset": 2})
        )
        assert len(page_two) == 1
        assert meta_two["total_count"] == 3
        assert meta_two["has_more"] is False

        returned = [record["id"] for record in page_one + page_two]
        assert sorted(returned) == sorted([store_a, store_b, store_c])
        assert store_d not in returned

    def test_out_of_range_pagination_is_refused_before_the_filter_runs(self, api, build):
        """limit 0, limit 500 and offset -1 are each rejected as invalid pagination.

        PRD 2.3: "A `limit` outside the inclusive range 1 through 100, a negative
        `offset`, or a non-integer value for either is rejected with
        `ERR_INVALID_PAGINATION` (HTTP 400)."

        Design: Corner/Entities/corner_invalid_pagination_arguments_returns_4XX_before_any_query
        """
        jurisdiction_id = build.jurisdiction(code="US-CA")
        store_id = build.store(jurisdiction_id)

        validate_error(
            api.list_scanner_audits(build.officer, {"store_id": store_id, "limit": 0, "offset": 0}),
            ERR_INVALID_PAGINATION,
        )
        validate_error(
            api.list_scanner_audits(
                build.officer, {"store_id": store_id, "limit": 500, "offset": 0}
            ),
            ERR_INVALID_PAGINATION,
        )
        validate_error(
            api.list_label_tasks(build.officer, {"store_id": store_id, "limit": 20, "offset": -1}),
            ERR_INVALID_PAGINATION,
        )

        audits, audits_meta = validate_paginated(
            api.list_scanner_audits(build.officer, {"store_id": store_id, "limit": 20, "offset": 0})
        )
        assert audits == []
        assert audits_meta["total_count"] == 0
        tasks, tasks_meta = validate_paginated(
            api.list_label_tasks(build.officer, {"store_id": store_id, "limit": 20, "offset": 0})
        )
        assert tasks == []
        assert tasks_meta["total_count"] == 0


class TestNotFoundCodes:
    def test_each_single_resource_read_answers_with_its_own_not_found_id(self, api, build):
        """Fifteen absent-id reads return fifteen pairwise-distinct 404 codes.

        PRD 2.10: "Every entity has its own not-found code, all of them HTTP 404:
        `ERR_JURISDICTION_NOT_FOUND`, `ERR_STORE_NOT_FOUND`,
        `ERR_AISLE_NOT_FOUND`, `ERR_ASSOCIATE_NOT_FOUND`,
        `ERR_PRICE_CHANGE_FILE_NOT_FOUND`, `ERR_PRICE_CHANGE_LINE_NOT_FOUND`,
        `ERR_LABEL_TASK_NOT_FOUND`, `ERR_SCANNER_AUDIT_NOT_FOUND`,
        `ERR_SCAN_LINE_NOT_FOUND`, `ERR_PROMO_SIGNAGE_NOT_FOUND`,
        `ERR_REGULATORY_INSPECTION_NOT_FOUND`,
        `ERR_INSPECTION_FINDING_NOT_FOUND`, `ERR_REFUND_CLAIM_NOT_FOUND`,
        `ERR_EXCEPTION_REPORT_NOT_FOUND`, and
        `ERR_ACCOUNTABILITY_ACTION_NOT_FOUND`."

        Design: Corner/Entities/corner_absent_identifiers_return_entity_specific_not_found
        """
        absent = NON_EXISTENT_UUID
        probes = [
            (api.get_jurisdiction(absent, build.admin), ERR_JURISDICTION_NOT_FOUND),
            (api.get_store(absent, build.admin), ERR_STORE_NOT_FOUND),
            (api.get_aisle(absent, build.admin), ERR_AISLE_NOT_FOUND),
            (api.get_associate(absent, build.admin), ERR_ASSOCIATE_NOT_FOUND),
            (api.get_price_change_file(absent, build.admin), ERR_PRICE_CHANGE_FILE_NOT_FOUND),
            (api.get_price_change_line(absent, build.admin), ERR_PRICE_CHANGE_LINE_NOT_FOUND),
            (api.get_label_task(absent, build.admin), ERR_LABEL_TASK_NOT_FOUND),
            (api.get_scanner_audit(absent, build.admin), ERR_SCANNER_AUDIT_NOT_FOUND),
            (api.get_scan_line(absent, build.admin), ERR_SCAN_LINE_NOT_FOUND),
            (api.get_promo_signage(absent, build.admin), ERR_PROMO_SIGNAGE_NOT_FOUND),
            (
                api.get_regulatory_inspection(absent, build.officer),
                ERR_REGULATORY_INSPECTION_NOT_FOUND,
            ),
            (api.get_inspection_finding(absent, build.officer), ERR_INSPECTION_FINDING_NOT_FOUND),
            (api.get_refund_claim(absent, build.desk), ERR_REFUND_CLAIM_NOT_FOUND),
            (api.get_exception_report(absent, build.officer), ERR_EXCEPTION_REPORT_NOT_FOUND),
            (
                api.get_accountability_action(absent, build.admin),
                ERR_ACCOUNTABILITY_ACTION_NOT_FOUND,
            ),
        ]

        seen = []
        for response, expected_error in probes:
            body = validate_error(response, expected_error)
            assert body["message"], f"{expected_error} carried an empty message"
            seen.append(body["error_id"])

        assert len(seen) == 15
        assert len(set(seen)) == 15

    def test_absent_path_parent_outranks_an_absent_body_reference(self, api, build):
        """An absent store in the path wins over an absent associate in the body.

        PRD 2.9: "**Priority 30 — path existence.** Every resource named by a path
        parameter exists, validated left to right in path order."
        PRD 2.9: "**Priority 32 — body reference existence.** Every foreign-key
        value supplied in the request body references an existing row, validated
        in the field order the endpoint declares its inputs."

        Design: Corner/Entities/corner_nested_creation_under_absent_parent_is_not_found_before_body_checks
        """
        jurisdiction_id = build.jurisdiction(code="US-CA")
        store_id = build.store(jurisdiction_id)

        nested_body = {
            "aisle_code": "A01",
            "category_code": "DAIRY",
            "assigned_associate_id": NON_EXISTENT_UUID,
        }
        validate_error(
            api.create_aisle(NON_EXISTENT_UUID, nested_body, build.admin), ERR_STORE_NOT_FOUND
        )
        validate_error(api.create_aisle(store_id, nested_body, build.admin), ERR_ASSOCIATE_NOT_FOUND)
        validate_error(
            api.create_price_change_line(
                NON_EXISTENT_UUID,
                {
                    "item_upc": "00000000002001",
                    "item_description": "Cheese 12oz",
                    "category_code": "DAIRY",
                    "old_retail_cents": 1199,
                    "new_retail_cents": 1000,
                    "net_content_qty": 12,
                    "net_content_uom": "OZ",
                },
                build.admin,
            ),
            ERR_PRICE_CHANGE_FILE_NOT_FOUND,
        )

        aisles, meta = validate_paginated(api.list_store_aisles(store_id, build.admin))
        assert aisles == []
        assert meta["total_count"] == 0


class TestScanLineImmutability:
    def test_scan_line_carries_no_version_and_no_updated_at(self, api, build):
        """An appended observation exposes its derived fields but no audit triplet.

        PRD 2.4: "The one exception is `ScanLine`: because a scan observation is
        immutable once appended, a `ScanLine` carries only `id` and `created_at`.
        It has no `updated_at` and no `version` field at all, and neither field
        should appear in its response payload."

        Design: Corner/Entities/corner_immutable_scan_line_has_no_version_and_no_mutator
        """
        jurisdiction_id = build.jurisdiction(code="US-CA")
        store_id = build.store(jurisdiction_id)
        aisle_id = build.aisle(store_id, aisle_code="A01", category_code="DAIRY")
        auditor_id = build.certified_auditor(store_id)
        auditor_headers = build.auditor(auditor_id)
        audit = build.scanner_audit(
            store_id,
            aisle_id,
            auditor_id,
            scan_window_start="2026-08-01T09:00:00Z",
            scan_window_end="2026-08-01T10:00:00Z",
            actor_headers=auditor_headers,
        )

        created = build.scan_line(
            audit["id"], "00000000002001", 1000, 1199, auditor_headers
        )
        assert_scan_line_shape(created)
        assert created["scanner_audit_id"] == audit["id"]
        assert created["item_upc"] == "00000000002001"
        assert_money_cents(created["shelf_price_cents"], 1000)
        assert_money_cents(created["register_price_cents"], 1199)
        assert created["variance_cents"] == 199
        assert created["classification"] == "OVERCHARGE"
        assert created["category_code"] == "DAIRY"

        read_back = validate_success(api.get_scan_line(created["id"], build.officer))
        assert_scan_line_shape(read_back)
        assert read_back == created


class TestCrossReferenceIntegrity:
    def test_each_cross_store_reference_fails_with_its_own_mismatch_code(self, api, build):
        """A foreign aisle, a foreign associate and an out-of-scope store fail differently.

        PRD 3.4: "The aisle must belong to the named store or the request fails
        with `ERR_AISLE_STORE_MISMATCH`; the assigned associate must belong to the
        named store or it fails with `ERR_ASSOCIATE_STORE_MISMATCH`; the store
        must appear in the batch's scope and share the batch's jurisdiction or it
        fails with `ERR_STORE_OUT_OF_FILE_SCOPE`".

        Design: Corner/Entities/corner_flat_topology_cross_reference_integrity_is_enforced
        """
        jurisdiction_id = build.jurisdiction(code="US-CA")
        store_a = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        store_b = build.store(jurisdiction_id, store_number="S002", name="Market Street")
        aisle_a1 = build.aisle(store_a, aisle_code="A01", category_code="DAIRY")
        aisle_b1 = build.aisle(store_b, aisle_code="B01", category_code="DAIRY")
        la1 = build.certified_label_associate(store_a, employee_number="E-LA1", full_name="Lee Label")
        la2 = build.certified_label_associate(store_b, employee_number="E-LA2", full_name="Lou Label")
        sm1 = build.certified_manager(store_a, employee_number="E-SM1")
        manager_headers = build.manager(sm1)

        distributed = build.distributed_file(
            jurisdiction_id,
            [store_a],
            [
                {
                    "item_upc": "00000000002001",
                    "new_retail_cents": 1000,
                    "old_retail_cents": 1199,
                    "net_content_qty": 12,
                    "net_content_uom": "OZ",
                    "item_description": "Cheese 12oz",
                }
            ],
            priority="ROUTINE",
        )
        file_id = distributed["file_id"]
        line_id = distributed["line_ids"][0]
        pinned = distributed["version"]

        def task_payload(store_id, aisle_id, associate_id):
            return {
                "store_id": store_id,
                "price_change_line_id": line_id,
                "aisle_id": aisle_id,
                "assigned_associate_id": associate_id,
                "scheduled_start_at": "2026-08-02T09:00:00Z",
                "scheduled_end_at": "2026-08-02T10:00:00Z",
                "expected_price_change_file_version": pinned,
            }

        validate_error(
            api.create_label_task(file_id, task_payload(store_a, aisle_b1, la1), manager_headers),
            ERR_AISLE_STORE_MISMATCH,
        )
        validate_error(
            api.create_label_task(file_id, task_payload(store_a, aisle_a1, la2), manager_headers),
            ERR_ASSOCIATE_STORE_MISMATCH,
        )
        validate_error(
            api.create_label_task(file_id, task_payload(store_b, aisle_b1, la2), manager_headers),
            ERR_STORE_OUT_OF_FILE_SCOPE,
        )

        tasks, meta = validate_paginated(
            api.list_label_tasks(build.admin, {"price_change_line_id": line_id})
        )
        assert tasks == []
        assert meta["total_count"] == 0
        assert build.read_file(file_id)["version"] == pinned
