"""Validation behaviour: conditional gates, the priority ladder, temporal and uniqueness rules."""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    assert_instant_is,
    assert_money_cents,
    assert_pct,
    assert_posture,
    factories,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_ACTION_INVALID_STATE,
    ERR_ASSOCIATE_NOT_CERTIFIED,
    ERR_ASSOCIATE_STORE_MISMATCH,
    ERR_AISLE_STORE_MISMATCH,
    ERR_AUDIT_NOT_CLOSED,
    ERR_AUDIT_SAMPLE_EMPTY,
    ERR_DENIAL_REASON_REQUIRED,
    ERR_DUPLICATE_RESOURCE,
    ERR_EFFECTIVE_DATE_PASSED,
    ERR_EXCEPTION_REPORT_INVALID_STATE,
    ERR_FILE_INVALID_STATE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_WINDOW,
    ERR_NOT_AN_OVERCHARGE,
    ERR_PRICE_CHANGE_FILE_NOT_FOUND,
    ERR_NO_QUALIFYING_AUDIT_DATA,
    ERR_REFUND_NOT_APPROVED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_PRICE_CHANGE_FILE_VERSION,
    ERR_STORE_NOT_FOUND,
    ERR_STORE_OUT_OF_FILE_SCOPE,
    ERR_STORE_POSTURE_BLOCKED,
    ERR_TRANSITION_ALREADY_APPLIED,
    ERR_UNIT_PRICE_UNAVAILABLE,
)
from test_helpers.constants import (
    POSTURE_FROZEN,
    POSTURE_OPEN,
    POSTURE_RESTRICTED,
    ROLE_CODE_LABEL_ASSOCIATE,
    ROLE_CODE_PRICE_AUDITOR,
    ROLE_CODE_STORE_MANAGER,
)


class TestActorCertificationGate:
    def test_the_gate_refuses_the_untrained_the_in_training_and_the_just_expired_auditor(
        self, api, build
    ):
        """Priority 51 is two predicates, and expiry is compared strictly.

        PRD 2.9: "**Priority 51 — actor certification.** The acting associate's
        `training_status` is `CERTIFIED` and their `certification_expires_at` is
        strictly after the current instant. Failure: `ERR_ASSOCIATE_NOT_CERTIFIED`
        (422). Applies to four endpoints: placement verification, scanner-audit
        creation, scan-line posting, and audit close."
        PRD 3.2: "A result of at least 80 taken while the associate is
        `UNTRAINED` or `IN_TRAINING` moves them to `CERTIFIED` and stamps
        `certification_expires_at` at the current instant plus 365 days."
        PRD 3.2: "A failing score for an `UNTRAINED` or `IN_TRAINING` associate
        is emphatically **not** an error — the attempt is recorded and the
        associate stays in training."
        PRD 3.5: "The first observation appended to an `OPEN` audit moves the
        audit `OPEN → SCANNING`"

        Design: Corner/Validations/corner_certification_gate_applies_with_and_without_a_live_certificate
        """
        jurisdiction_id = build.jurisdiction(code="US-CA")
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        aisle_id = build.aisle(store_id, aisle_code="A01", category_code="DAIRY")
        auditor_id = build.associate(
            store_id,
            ROLE_CODE_PRICE_AUDITOR,
            employee_number="E-PA1",
            full_name="Pat Auditor",
        )
        hired = build.read_associate(auditor_id)
        assert hired["training_status"] == "UNTRAINED"
        assert hired["certification_expires_at"] is None

        auditor_headers = build.auditor(auditor_id)
        audit_payload = factories.scanner_audit_payload(
            store_id,
            aisle_id,
            auditor_id,
            "2026-08-02T08:00:00Z",
            "2026-08-02T09:00:00Z",
            "ROUTINE",
        )
        validate_error(
            api.create_scanner_audit(audit_payload, auditor_headers),
            ERR_ASSOCIATE_NOT_CERTIFIED,
            422,
        )

        failing = build.train(auditor_id, "AUDIT_101", 79)
        assert failing["training_status"] == "IN_TRAINING"
        assert failing["certification_expires_at"] is None
        assert failing["last_training_score_pct"] == pytest.approx(79, abs=0.01)
        validate_error(
            api.create_scanner_audit(audit_payload, auditor_headers),
            ERR_ASSOCIATE_NOT_CERTIFIED,
            422,
        )

        passing = build.train(auditor_id, "AUDIT_101", 80)
        assert passing["training_status"] == "CERTIFIED"
        assert_instant_is(passing["certification_expires_at"], "2027-08-01T00:00:00Z")

        audit = validate_success(
            api.create_scanner_audit(audit_payload, auditor_headers), 201
        )
        assert audit["status"] == "OPEN"

        scan_payload = factories.scan_line_payload("00000000006001", 100, 150)
        build.set_clock("2027-08-01T00:00:00Z")
        validate_error(
            api.create_scan_line(audit["id"], scan_payload, auditor_headers),
            ERR_ASSOCIATE_NOT_CERTIFIED,
            422,
        )

        build.set_clock("2026-08-02T08:30:00Z")
        observation = validate_success(
            api.create_scan_line(audit["id"], scan_payload, auditor_headers), 201
        )
        assert observation["classification"] == "OVERCHARGE"
        scanning = build.read_audit(audit["id"])
        assert scanning["status"] == "SCANNING"
        assert scanning["sample_size"] == 1


class TestPostureGate:
    def test_restricted_yields_to_the_override_while_frozen_refuses_every_write_point(
        self, api, build, admin_headers
    ):
        """One failed audit restricts and can be overridden; two freeze outright.

        PRD 2.9: "**Priority 52 — posture gate.** A `FROZEN` store blocks
        label-task creation, label printing and signage posting outright; a
        `RESTRICTED` store blocks signage posting unless the request sets
        `override_acknowledged` to true. Failure: `ERR_STORE_POSTURE_BLOCKED`
        (422). Applies to three endpoints: label-task creation, label printing,
        and signage posting."
        PRD 2.7: "The posture becomes `FROZEN` when at least one escalated
        finding exists, **or** when the open finding count is at least 3, **or**
        when the thirty-day failed-audit count is at least 2. Otherwise the
        posture becomes `RESTRICTED` when the open finding count is at least 1,
        **or** when the thirty-day failed-audit count is exactly 1, **or** when
        the label backlog is at least 5, **or** when at least one signage
        violation exists."
        PRD 3.6: "And the store's posture must permit it: a `FROZEN` store
        refuses the post outright, and a `RESTRICTED` store refuses it unless
        the request sets `override_acknowledged` to true **and** the sign names
        a `price_change_line_id`, both refusals carrying
        `ERR_STORE_POSTURE_BLOCKED`."
        PRD 3.2: "Under `OCCURRENCE_WEIGHTED`, the score is 100 reduced by the
        sum of the weights of the outstanding actions, floored at zero"

        Design: Corner/Validations/corner_posture_gate_blocks_restricted_without_override_and_frozen_outright
        """
        jurisdiction_id = build.jurisdiction(
            code="US-CA",
            scanner_error_rate_threshold_pct=20.0,
            grace_period_hours=48,
            signage_disclosure_codes=[],
        )
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        assert_posture(build.read_store(store_id), POSTURE_OPEN)

        manager_id = build.certified(
            store_id,
            ROLE_CODE_STORE_MANAGER,
            employee_number="E-SM1",
            full_name="Sam Manager",
        )
        label_id = build.certified(
            store_id,
            ROLE_CODE_LABEL_ASSOCIATE,
            employee_number="E-LA1",
            full_name="Lee Label",
        )
        auditor_id = build.certified(
            store_id,
            ROLE_CODE_PRICE_AUDITOR,
            module_code="AUDIT_101",
            employee_number="E-PA1",
            full_name="Pat Auditor",
        )
        manager_headers = build.manager(manager_id)
        aisle_dairy = build.aisle(
            store_id,
            aisle_code="A01",
            category_code="DAIRY",
            assigned_associate_id=label_id,
        )
        aisle_bakery = build.aisle(store_id, aisle_code="A02", category_code="BAKERY")
        aisle_candy = build.aisle(store_id, aisle_code="A03", category_code="CANDY")

        built = build.distributed_file(
            jurisdiction_id,
            [store_id],
            [
                {
                    "item_upc": "00000000007001",
                    "new_retail_cents": 449,
                    "old_retail_cents": 499,
                    "net_content_qty": 1,
                    "net_content_uom": "GAL",
                    "item_description": "Milk 1 GAL",
                    "category_code": "DAIRY",
                },
                {
                    "item_upc": "00000000007002",
                    "new_retail_cents": 349,
                    "old_retail_cents": 399,
                    "net_content_qty": 24,
                    "net_content_uom": "OZ",
                    "item_description": "Bread 24 OZ",
                    "category_code": "BAKERY",
                },
            ],
            file_number="PCF-1",
        )
        assert built["file"]["status"] == "DISTRIBUTED"
        line_dairy, line_bakery = built["line_ids"]

        task = build.label_task(
            built["file_id"],
            store_id,
            line_dairy,
            aisle_dairy,
            label_id,
            scheduled_start_at="2026-08-02T08:00:00Z",
            scheduled_end_at="2026-08-02T10:00:00Z",
            expected_price_change_file_version=built["version"],
        )
        sign_one = build.promo_signage(
            store_id,
            aisle_bakery,
            [],
            actor_headers=manager_headers,
            sign_code="SG-1",
            promo_start_at="2026-08-01T00:00:00Z",
            promo_end_at="2026-08-10T00:00:00Z",
            price_change_line_id=line_bakery,
        )
        sign_two = build.promo_signage(
            store_id,
            aisle_candy,
            [],
            actor_headers=manager_headers,
            sign_code="SG-2",
            promo_start_at="2026-08-01T00:00:00Z",
            promo_end_at="2026-08-10T00:00:00Z",
            price_change_line_id=line_dairy,
        )

        first = build.closed_audit(
            store_id,
            aisle_dairy,
            auditor_id,
            [
                {
                    "item_upc": "00000000007001",
                    "shelf_price_cents": 100,
                    "register_price_cents": 150,
                }
            ],
            rate_variant="GROSS_MISMATCH",
        )
        assert_pct(first["audit"]["error_rate_pct"], 100.00)
        assert first["audit"]["outcome"] == "FAIL"

        restricted = build.read_store(store_id)
        assert restricted["failed_audit_count_30d"] == 1
        assert restricted["label_backlog_count"] == 1
        assert_posture(restricted, POSTURE_RESTRICTED)
        penalised = build.read_associate(label_id)
        assert_pct(penalised["accountability_score"], 85)
        assert penalised["training_status"] == "CERTIFIED"

        validate_error(
            api.post_promo_signage(sign_one["id"], manager_headers),
            ERR_STORE_POSTURE_BLOCKED,
            422,
        )
        overridden = build.post_signage(
            sign_one["id"], manager_headers, override_acknowledged=True
        )
        assert overridden["status"] == "POSTED"
        assert overridden["compliance_state"] == "COMPLIANT"

        second = build.closed_audit(
            store_id,
            aisle_bakery,
            auditor_id,
            [
                {
                    "item_upc": "00000000007002",
                    "shelf_price_cents": 200,
                    "register_price_cents": 250,
                }
            ],
            rate_variant="GROSS_MISMATCH",
            scan_window_start="2026-08-01T10:00:00Z",
            scan_window_end="2026-08-01T11:00:00Z",
        )
        assert second["audit"]["outcome"] == "FAIL"
        frozen = build.read_store(store_id)
        assert frozen["failed_audit_count_30d"] == 2
        assert_posture(frozen, POSTURE_FROZEN)

        validate_error(
            api.post_promo_signage(
                sign_two["id"],
                manager_headers,
                factories.post_signage_payload(override_acknowledged=True),
            ),
            ERR_STORE_POSTURE_BLOCKED,
            422,
        )
        assert build.read_signage(sign_two["id"])["status"] == "DRAFT"

        validate_error(
            api.print_label_task(task["id"], build.associate_headers(label_id)),
            ERR_STORE_POSTURE_BLOCKED,
            422,
        )
        owning = build.read_file(built["file_id"])
        assert owning["status"] == "PARTIALLY_EXECUTED"

        blocked = factories.label_task_payload(
            store_id,
            line_bakery,
            aisle_bakery,
            label_id,
            "2026-08-02T12:00:00Z",
            "2026-08-02T14:00:00Z",
            owning["version"],
        )
        validate_error(
            api.create_label_task(built["file_id"], blocked, manager_headers),
            ERR_STORE_POSTURE_BLOCKED,
            422,
        )
        rows, meta = validate_paginated(
            api.list_label_tasks(admin_headers, {"store_id": store_id})
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [task["id"]]


class TestUndisplayableUnitPrice:
    def test_the_refusal_keys_on_the_uom_rule_and_not_on_the_required_flag(
        self, api, build, admin_headers
    ):
        """A jurisdiction that does not require unit prices still cannot task a zero-content line.

        PRD 2.9: "**Priority 54 — undisplayable unit price.** A line whose unit
        price cannot be displayed cannot be tasked for labelling: this is the
        case when `net_content_qty` is not positive while the jurisdiction's
        `unit_price_uom_rule` is something other than `PER_SINGLE_ITEM`. This
        rule keys on `unit_price_uom_rule` alone. `unit_price_required` governs
        only the distribution precondition, so a jurisdiction with
        `unit_price_required` set to false distributes such a file happily and
        still refuses to task the line. Failure: `ERR_UNIT_PRICE_UNAVAILABLE`
        (422). Applies to label-task creation."
        PRD 3.3: "If the basis quantity works out to exactly zero — reachable
        only when the net content quantity is zero under a rule other than
        `PER_SINGLE_ITEM` — the computation stops there without attempting any
        division: all three of `unit_price_display_cents`,
        `unit_price_basis_qty` and `unit_price_basis_uom` are left null and the
        line is still created."
        PRD 3.4: "`due_at` is the effective date of the batch that owns the
        line, advanced by the jurisdiction's grace period in hours"

        Design: Corner/Validations/corner_unit_price_unavailable_gate_is_keyed_on_the_uom_rule_alone
        """
        jurisdiction_id = build.jurisdiction(
            code="US-NV",
            name="Nevada",
            unit_price_required=False,
            grace_period_hours=48,
        )
        rulebook = build.read_jurisdiction(jurisdiction_id)
        assert rulebook["unit_price_required"] is False
        assert rulebook["unit_price_uom_rule"] == "PER_UNIT_MEASURE_CANONICAL"

        store_id = build.store(
            jurisdiction_id, store_number="S002", name="Desert Road"
        )
        manager_id = build.certified(
            store_id,
            ROLE_CODE_STORE_MANAGER,
            employee_number="E-SM2",
            full_name="Sky Manager",
        )
        label_id = build.certified(
            store_id,
            ROLE_CODE_LABEL_ASSOCIATE,
            employee_number="E-LA2",
            full_name="Lou Label",
        )
        manager_headers = build.manager(manager_id)
        aisle_id = build.aisle(
            store_id,
            aisle_code="B01",
            category_code="MEAT",
            assigned_associate_id=label_id,
        )

        file_record = build.price_change_file(
            jurisdiction_id,
            [store_id],
            effective_date="2026-08-03T00:00:00Z",
            file_number="PCF-2",
        )
        file_id = file_record["id"]
        zero_line = build.add_line(
            file_id,
            item_upc="00000000008001",
            new_retail_cents=1299,
            old_retail_cents=0,
            net_content_qty=0,
            net_content_uom="LB",
            item_description="Bulk beef",
            category_code="MEAT",
        )
        assert zero_line["unit_price_display_cents"] is None
        assert zero_line["unit_price_basis_qty"] is None
        assert zero_line["unit_price_basis_uom"] is None

        good_line = build.add_line(
            file_id,
            item_upc="00000000008002",
            new_retail_cents=800,
            old_retail_cents=899,
            net_content_qty=2,
            net_content_uom="LB",
            item_description="Steak 2 LB",
            category_code="MEAT",
        )
        assert_money_cents(good_line["unit_price_display_cents"], 400)
        assert good_line["unit_price_basis_qty"] == pytest.approx(2, abs=0.000001)
        assert good_line["unit_price_basis_uom"] == "LB"

        distributed = build.distribute(file_id)
        assert distributed["status"] == "DISTRIBUTED"

        refused = factories.label_task_payload(
            store_id,
            zero_line["id"],
            aisle_id,
            label_id,
            "2026-08-04T08:00:00Z",
            "2026-08-04T10:00:00Z",
            distributed["version"],
        )
        validate_error(
            api.create_label_task(file_id, refused, manager_headers),
            ERR_UNIT_PRICE_UNAVAILABLE,
            422,
        )

        accepted = factories.label_task_payload(
            store_id,
            good_line["id"],
            aisle_id,
            label_id,
            "2026-08-04T08:00:00Z",
            "2026-08-04T10:00:00Z",
            distributed["version"],
        )
        validate_success(
            api.create_label_task(file_id, accepted, manager_headers), 201
        )

        build.amend_jurisdiction(
            jurisdiction_id, {"unit_price_uom_rule": "PER_SINGLE_ITEM"}
        )
        untouched = build.read_line(zero_line["id"])
        assert untouched["unit_price_display_cents"] is None
        assert untouched["unit_price_basis_qty"] is None
        assert untouched["unit_price_basis_uom"] is None

        now_allowed = factories.label_task_payload(
            store_id,
            zero_line["id"],
            aisle_id,
            label_id,
            "2026-08-04T12:00:00Z",
            "2026-08-04T14:00:00Z",
            build.file_version(file_id),
        )
        task = validate_success(
            api.create_label_task(file_id, now_allowed, manager_headers), 201
        )
        assert_instant_is(task["due_at"], "2026-08-05T00:00:00Z")

        rows, meta = validate_paginated(
            api.list_label_tasks(admin_headers, {"store_id": store_id})
        )
        assert meta["total_count"] == 2
        assert len(rows) == 2


class TestPriorityLadder:
    def test_each_probe_reports_the_highest_ranked_of_its_several_violations(
        self, api, build, admin_headers
    ):
        """Nine label-task probes, each breaking two or more rules at once.

        PRD 2.9: "**Priority 25 — schema.** The request body parses, every
        required input field is present, enum values are members of their
        declared sets, integer fields are integers within range, timestamps are
        RFC 3339, and array fields are arrays. Failure: `ERR_INVALID_REQUEST`
        (400). Applies to every endpoint."
        PRD 2.9: "**Priority 30 — path existence.** Every resource named by a
        path parameter exists, validated left to right in path order."
        PRD 2.9: "**Priority 32 — body reference existence.** Every foreign-key
        value supplied in the request body references an existing row, validated
        in the field order the endpoint declares its inputs."
        PRD 2.9: "**Priority 45 — version pinning.** When the request carries a
        version-pinning field, it equals the referenced entity's current
        `version`."
        PRD 2.9: "**Priority 58 — well-formed intervals.** Declared intervals
        must have a start strictly before their end: `promo_start_at` before
        `promo_end_at`, `scan_window_start` before `scan_window_end`,
        `scheduled_start_at` before `scheduled_end_at`, and `period_start_at`
        before `period_end_at`. Failure: `ERR_INVALID_WINDOW` (422). Applies to
        four endpoints: signage creation, scanner-audit creation, label-task
        creation, and exception-report creation."
        PRD 2.9: "**Priority 66 — aisle/store agreement.** The aisle named by
        `aisle_id` must belong to the store named by `store_id`. Failure:
        `ERR_AISLE_STORE_MISMATCH` (422). Applies to three endpoints:
        scanner-audit creation, signage creation, and label-task creation."
        PRD 2.9: "**Priority 67 — associate/store agreement.** The associate
        named by an assignment or actor field must belong to the store the
        operation targets. Failure: `ERR_ASSOCIATE_STORE_MISMATCH` (422)."
        PRD 2.9: "**Priority 68 — file scope.** The store must be present in the
        price change file's `scope_store_ids` and must share the file's
        `jurisdiction_id`. Failure: `ERR_STORE_OUT_OF_FILE_SCOPE` (422). Applies
        to label-task creation."
        PRD 3.4: "Tasking is refused outright when the batch is neither
        `DISTRIBUTED` nor `PARTIALLY_EXECUTED`, which surfaces as
        `ERR_FILE_INVALID_STATE`."
        PRD 2.9: "Label-task creation is the most heavily guarded endpoint in the
        service, and the ladder above fixes the order in which its guards fire:
        existence of the file and of every referenced row, then the file's own
        state, then the version pin, then the posture gate, then the
        undisplayable-unit-price refusal, then the well-formed-interval test,
        then the schedule-overlap test, then the duplicate-task test, then
        aisle/store agreement, then associate/store agreement, then file scope,
        and only then the daily minutes cap."

        Design: Corner/Validations/corner_priority_ladder_returns_4XX_of_the_highest_ranked_violation
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
        manager_headers = build.manager(manager_id)
        aisle_a = build.aisle(store_a, aisle_code="A01", category_code="DAIRY")
        aisle_b = build.aisle(store_b, aisle_code="B01", category_code="DAIRY")

        draft = build.price_change_file(
            jurisdiction_id, [store_a], file_number="PCF-1"
        )
        file_id = draft["id"]
        stale_version = draft["version"]
        line_1 = build.add_line(
            file_id,
            item_upc="00000000009001",
            new_retail_cents=449,
            old_retail_cents=499,
            net_content_qty=1,
            net_content_uom="GAL",
            item_description="Milk 1 GAL",
            category_code="DAIRY",
        )["id"]
        line_2 = build.add_line(
            file_id,
            item_upc="00000000009002",
            new_retail_cents=549,
            old_retail_cents=599,
            net_content_qty=8,
            net_content_uom="OZ",
            item_description="Cheese 8 OZ",
            category_code="DAIRY",
        )["id"]
        distributed = build.distribute(file_id)
        build.label_task(
            file_id,
            store_a,
            line_1,
            aisle_a,
            label_a,
            scheduled_start_at="2026-08-02T08:00:00Z",
            scheduled_end_at="2026-08-02T10:00:00Z",
            expected_price_change_file_version=distributed["version"],
        )
        current_version = build.file_version(file_id)

        other = build.price_change_file(
            jurisdiction_id, [store_a], file_number="PCF-DRAFT"
        )
        draft_line = build.add_line(
            other["id"],
            item_upc="00000000009003",
            new_retail_cents=649,
            old_retail_cents=699,
            net_content_qty=16,
            net_content_uom="OZ",
            item_description="Butter 16 OZ",
            category_code="DAIRY",
        )["id"]

        def probe(path_file_id, payload):
            return api.create_label_task(path_file_id, payload, manager_headers)

        malformed = factories.label_task_payload(
            NON_EXISTENT_UUID,
            line_2,
            aisle_a,
            label_a,
            "not-a-timestamp",
            "2026-08-02T14:00:00Z",
            current_version,
        )
        validate_error(
            probe(NON_EXISTENT_UUID, malformed), ERR_INVALID_REQUEST, 400
        )

        missing_file = factories.label_task_payload(
            NON_EXISTENT_UUID,
            line_2,
            aisle_a,
            label_a,
            "2026-08-02T12:00:00Z",
            "2026-08-02T14:00:00Z",
            current_version,
        )
        validate_error(
            probe(NON_EXISTENT_UUID, missing_file),
            ERR_PRICE_CHANGE_FILE_NOT_FOUND,
            404,
        )

        missing_store = factories.label_task_payload(
            NON_EXISTENT_UUID,
            line_2,
            NON_EXISTENT_UUID,
            label_a,
            "2026-08-02T12:00:00Z",
            "2026-08-02T14:00:00Z",
            current_version,
        )
        validate_error(probe(file_id, missing_store), ERR_STORE_NOT_FOUND, 404)

        wrong_state = factories.label_task_payload(
            store_a,
            draft_line,
            aisle_a,
            label_a,
            "2026-08-02T12:00:00Z",
            "2026-08-02T14:00:00Z",
            stale_version,
        )
        validate_error(
            probe(other["id"], wrong_state), ERR_FILE_INVALID_STATE, 409
        )

        stale_pin = factories.label_task_payload(
            store_a,
            line_2,
            aisle_a,
            label_a,
            "2026-08-02T14:00:00Z",
            "2026-08-02T14:00:00Z",
            stale_version,
        )
        validate_error(
            probe(file_id, stale_pin), ERR_STALE_PRICE_CHANGE_FILE_VERSION, 412
        )

        degenerate = factories.label_task_payload(
            store_a,
            line_1,
            aisle_a,
            label_a,
            "2026-08-02T14:00:00Z",
            "2026-08-02T14:00:00Z",
            current_version,
        )
        validate_error(probe(file_id, degenerate), ERR_INVALID_WINDOW, 422)

        foreign_aisle = factories.label_task_payload(
            store_a,
            line_2,
            aisle_b,
            label_b,
            "2026-08-02T12:00:00Z",
            "2026-08-02T14:00:00Z",
            current_version,
        )
        validate_error(probe(file_id, foreign_aisle), ERR_AISLE_STORE_MISMATCH, 422)

        foreign_associate = factories.label_task_payload(
            store_b,
            line_2,
            aisle_b,
            label_a,
            "2026-08-02T12:00:00Z",
            "2026-08-02T14:00:00Z",
            current_version,
        )
        validate_error(
            probe(file_id, foreign_associate), ERR_ASSOCIATE_STORE_MISMATCH, 422
        )

        out_of_scope = factories.label_task_payload(
            store_b,
            line_2,
            aisle_b,
            label_b,
            "2026-08-02T12:00:00Z",
            "2026-08-02T14:00:00Z",
            current_version,
        )
        validate_error(
            probe(file_id, out_of_scope), ERR_STORE_OUT_OF_FILE_SCOPE, 422
        )

        assert build.file_version(file_id) == current_version
        _rows, meta = validate_paginated(
            api.list_label_tasks(admin_headers, {"price_change_line_id": line_2})
        )
        assert meta["total_count"] == 0


class TestTemporalWindows:
    def test_the_deadline_is_strict_and_one_code_covers_every_degenerate_interval(
        self, api, build, officer_headers
    ):
        """One second before the deadline distributes; the deadline instant does not.

        PRD 2.9: "**Priority 56 — distribution deadline.** A price change file
        may only be distributed while the current instant is strictly before its
        effective date plus the jurisdiction's grace period. Failure:
        `ERR_EFFECTIVE_DATE_PASSED` (422). Applies to file distribution."
        PRD 3.3: "It also has a deadline: distribution is permitted only while
        the current instant is strictly before the batch's effective date plus
        the jurisdiction's grace period — with the default 48-hour grace period,
        a batch effective at noon on the first may still be distributed at 11:59
        on the third but not at noon on the third, and a late attempt is refused
        with `ERR_EFFECTIVE_DATE_PASSED`."
        PRD 2.9: "Declared intervals must have a start strictly before their end:
        `promo_start_at` before `promo_end_at`, `scan_window_start` before
        `scan_window_end`, `scheduled_start_at` before `scheduled_end_at`, and
        `period_start_at` before `period_end_at`. Failure: `ERR_INVALID_WINDOW`
        (422). Applies to four endpoints: signage creation, scanner-audit
        creation, label-task creation, and exception-report creation."

        Design: Corner/Validations/corner_temporal_windows_reject_degenerate_intervals_and_the_passed_deadline
        """
        jurisdiction_id = build.jurisdiction(code="US-CA", grace_period_hours=48)
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        manager_id = build.certified(
            store_id,
            ROLE_CODE_STORE_MANAGER,
            employee_number="E-SM1",
            full_name="Sam Manager",
        )
        label_id = build.certified(
            store_id,
            ROLE_CODE_LABEL_ASSOCIATE,
            employee_number="E-LA1",
            full_name="Lee Label",
        )
        auditor_id = build.certified(
            store_id,
            ROLE_CODE_PRICE_AUDITOR,
            module_code="AUDIT_101",
            employee_number="E-PA1",
            full_name="Pat Auditor",
        )
        manager_headers = build.manager(manager_id)
        aisle_id = build.aisle(
            store_id,
            aisle_code="A01",
            category_code="DAIRY",
            assigned_associate_id=label_id,
        )

        ok_file = build.price_change_file(
            jurisdiction_id, [store_id], file_number="PCF-OK"
        )
        ok_line = build.add_line(
            ok_file["id"],
            item_upc="00000000010001",
            new_retail_cents=449,
            old_retail_cents=499,
            net_content_qty=1,
            net_content_uom="GAL",
            item_description="Milk 1 GAL",
            category_code="DAIRY",
        )["id"]
        late_file = build.price_change_file(
            jurisdiction_id, [store_id], file_number="PCF-LATE"
        )
        build.add_line(
            late_file["id"],
            item_upc="00000000010002",
            new_retail_cents=549,
            old_retail_cents=599,
            net_content_qty=8,
            net_content_uom="OZ",
            item_description="Cheese 8 OZ",
            category_code="DAIRY",
        )

        build.set_clock("2026-08-04T23:59:59Z")
        distributed = validate_success(
            api.distribute_price_change_file(ok_file["id"], build.admin)
        )
        assert distributed["status"] == "DISTRIBUTED"
        assert_instant_is(distributed["distributed_at"], "2026-08-04T23:59:59Z")

        build.set_clock("2026-08-05T00:00:00Z")
        validate_error(
            api.distribute_price_change_file(late_file["id"], build.admin),
            ERR_EFFECTIVE_DATE_PASSED,
            422,
        )
        assert build.read_file(late_file["id"])["status"] == "DRAFT"

        sign_payload = factories.promo_signage_payload(
            store_id,
            aisle_id,
            [],
            promo_start_at="2026-08-06T00:00:00Z",
            promo_end_at="2026-08-06T00:00:00Z",
            sign_code="SG-1",
        )
        validate_error(
            api.create_promo_signage(sign_payload, manager_headers),
            ERR_INVALID_WINDOW,
            422,
        )

        audit_payload = factories.scanner_audit_payload(
            store_id,
            aisle_id,
            auditor_id,
            "2026-08-06T10:00:00Z",
            "2026-08-06T09:00:00Z",
        )
        validate_error(
            api.create_scanner_audit(audit_payload, build.auditor(auditor_id)),
            ERR_INVALID_WINDOW,
            422,
        )

        task_payload = factories.label_task_payload(
            store_id,
            ok_line,
            aisle_id,
            label_id,
            "2026-08-06T08:00:00Z",
            "2026-08-06T08:00:00Z",
            distributed["version"],
        )
        validate_error(
            api.create_label_task(ok_file["id"], task_payload, manager_headers),
            ERR_INVALID_WINDOW,
            422,
        )

        backwards = factories.exception_report_payload(
            store_id, "2026-08-04T00:00:00Z", "2026-08-03T00:00:00Z"
        )
        validate_error(
            api.create_exception_report(backwards, officer_headers),
            ERR_INVALID_WINDOW,
            422,
        )

        well_formed = factories.exception_report_payload(
            store_id, "2026-08-03T00:00:00Z", "2026-08-04T00:00:00Z"
        )
        validate_error(
            api.create_exception_report(well_formed, officer_headers),
            ERR_NO_QUALIFYING_AUDIT_DATA,
            422,
        )

        _rows, meta = validate_paginated(
            api.list_exception_reports(officer_headers, {"store_id": store_id})
        )
        assert meta["total_count"] == 0


class TestUniquenessTuples:
    def test_the_same_line_and_the_same_sign_code_are_free_in_a_different_store(
        self, api, build, admin_headers
    ):
        """Each uniqueness key is a tuple that includes the store.

        PRD 2.9: "**Priority 63 — uniqueness.** One label task per line-and-store
        pair; one `sign_code` per store; one open exception report per
        store-and-period triple; one refund claim per scan-line-and-customer
        pair. Failure: `ERR_DUPLICATE_RESOURCE` (409). Applies to four endpoints:
        label-task creation, signage creation, exception-report creation, and
        refund-claim creation."
        PRD 3.4: "Labour intervals for one assignee may not touch or overlap:
        because the comparison uses closed-closed semantics, a new interval that
        begins at the exact instant an existing non-terminal task of the same
        assignee ends is already a conflict, refused with
        `ERR_ASSOCIATE_SCHEDULE_CONFLICT`."

        Design: Corner/Validations/corner_uniqueness_keys_are_scoped_to_their_declared_tuple
        """
        jurisdiction_id = build.jurisdiction(code="US-CA", grace_period_hours=48)
        store_a = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        store_b = build.store(jurisdiction_id, store_number="S002", name="Elm Plaza")
        manager_a = build.certified(
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
        manager_b = build.certified(
            store_b,
            ROLE_CODE_STORE_MANAGER,
            employee_number="E-SM2",
            full_name="Mel Manager",
        )
        label_b = build.certified(
            store_b,
            ROLE_CODE_LABEL_ASSOCIATE,
            employee_number="E-LB1",
            full_name="Bo Label",
        )
        headers_a = build.manager(manager_a)
        headers_b = build.manager(manager_b)
        aisle_a = build.aisle(
            store_a,
            aisle_code="A01",
            category_code="DAIRY",
            assigned_associate_id=label_a,
        )
        aisle_b = build.aisle(
            store_b,
            aisle_code="B01",
            category_code="DAIRY",
            assigned_associate_id=label_b,
        )

        built = build.distributed_file(
            jurisdiction_id,
            [store_a, store_b],
            [
                {
                    "item_upc": "00000000011001",
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
        file_id = built["file_id"]
        line_id = built["line_ids"][0]
        distributed_version = built["version"]

        first = validate_success(
            api.create_label_task(
                file_id,
                factories.label_task_payload(
                    store_a,
                    line_id,
                    aisle_a,
                    label_a,
                    "2026-08-02T08:00:00Z",
                    "2026-08-02T10:00:00Z",
                    distributed_version,
                ),
                headers_a,
            ),
            201,
        )
        after_first = build.read_file(file_id)
        assert after_first["status"] == "PARTIALLY_EXECUTED"
        assert after_first["version"] == distributed_version + 1

        validate_error(
            api.create_label_task(
                file_id,
                factories.label_task_payload(
                    store_a,
                    line_id,
                    aisle_a,
                    label_a,
                    "2026-08-02T12:00:00Z",
                    "2026-08-02T14:00:00Z",
                    after_first["version"],
                ),
                headers_a,
            ),
            ERR_DUPLICATE_RESOURCE,
            409,
        )

        second = validate_success(
            api.create_label_task(
                file_id,
                factories.label_task_payload(
                    store_b,
                    line_id,
                    aisle_b,
                    label_b,
                    "2026-08-02T08:00:00Z",
                    "2026-08-02T10:00:00Z",
                    after_first["version"],
                ),
                headers_b,
            ),
            201,
        )
        assert second["id"] != first["id"]

        sign_a = validate_success(
            api.create_promo_signage(
                factories.promo_signage_payload(
                    store_a,
                    aisle_a,
                    [],
                    sign_code="SG-1",
                    promo_start_at="2026-08-02T00:00:00Z",
                    promo_end_at="2026-08-09T00:00:00Z",
                ),
                headers_a,
            ),
            201,
        )
        validate_error(
            api.create_promo_signage(
                factories.promo_signage_payload(
                    store_a,
                    aisle_a,
                    [],
                    sign_code="SG-1",
                    promo_start_at="2026-08-03T00:00:00Z",
                    promo_end_at="2026-08-10T00:00:00Z",
                ),
                headers_a,
            ),
            ERR_DUPLICATE_RESOURCE,
            409,
        )
        sign_b = validate_success(
            api.create_promo_signage(
                factories.promo_signage_payload(
                    store_b,
                    aisle_b,
                    [],
                    sign_code="SG-1",
                    promo_start_at="2026-08-02T00:00:00Z",
                    promo_end_at="2026-08-09T00:00:00Z",
                ),
                headers_b,
            ),
            201,
        )
        assert sign_b["id"] != sign_a["id"]

        _rows, meta = validate_paginated(
            api.list_label_tasks(admin_headers, {"price_change_line_id": line_id})
        )
        assert meta["total_count"] == 2


class TestRefundChainOrder:
    def test_each_refund_gate_only_becomes_reachable_once_the_previous_one_passes(
        self, api, build, admin_headers, desk_headers
    ):
        """Closure, then classification, then uniqueness, then the settlement guards.

        PRD 3.8: "The scan line's owning audit must be `CLOSED`, refusing an
        in-flight audit with `ERR_AUDIT_NOT_CLOSED`."
        PRD 2.9: "Because an open audit necessarily has zero scan lines, a close
        attempt against an open audit is reported by the empty-sample rule at
        priority 63 as `ERR_AUDIT_SAMPLE_EMPTY` rather than by this rule."
        PRD 3.8: "The scan line's `classification` must be `OVERCHARGE` — that
        is, its `register_price_cents` must exceed its `shelf_price_cents` —
        refusing a matching or undercharged line with `ERR_NOT_AN_OVERCHARGE`."
        PRD 3.8: "Only one claim may exist per scan-line-and-customer pair, a
        repeat yielding `ERR_DUPLICATE_RESOURCE`; a second, different customer
        may legitimately claim against the same observation."
        PRD 3.8: "Under `REFUND_DIFFERENCE_ONLY` the gross amount is that
        variance alone."
        PRD 3.8: "Requesting payment on a claim whose status is anything other
        than `APPROVED` is refused with `ERR_REFUND_NOT_APPROVED`; any other
        disallowed settlement transition, such as approving a denied claim or
        denying a paid one, is refused with `ERR_REFUND_CLAIM_INVALID_STATE`;
        and repeating a settlement that has already been applied, such as paying
        an already-`PAID` claim, is refused with
        `ERR_TRANSITION_ALREADY_APPLIED`."
        PRD 3.8: "Denial is the compensating operation of this ledger, and a
        denial with no `denial_reason`, or an empty one, is refused with
        `ERR_DENIAL_REASON_REQUIRED`."

        Design: Corner/Validations/corner_refund_claim_checks_run_in_declared_chain_order
        """
        jurisdiction_id = build.jurisdiction(code="US-CA")
        rulebook = build.read_jurisdiction(jurisdiction_id)
        assert rulebook["overcharge_refund_policy"] == "REFUND_DIFFERENCE_ONLY"
        assert_money_cents(rulebook["refund_cap_cents"], 5000)
        assert_money_cents(rulebook["refund_budget_per_audit_cents"], 100000)

        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
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
        aisle_id = build.aisle(store_id, aisle_code="A01", category_code="DAIRY")

        evidence = build.audit_with_scan_lines(
            store_id,
            aisle_id,
            auditor_id,
            [
                {
                    "item_upc": "00000000012001",
                    "shelf_price_cents": 100,
                    "register_price_cents": 299,
                },
                {
                    "item_upc": "00000000012002",
                    "shelf_price_cents": 100,
                    "register_price_cents": 100,
                },
            ],
            audit_type="FOLLOW_UP",
            scan_window_start="2026-08-01T08:00:00Z",
            scan_window_end="2026-08-01T09:00:00Z",
        )
        overcharge_line, matching_line = evidence["scan_lines"]
        assert_money_cents(overcharge_line["variance_cents"], 199)
        assert overcharge_line["classification"] == "OVERCHARGE"
        assert matching_line["classification"] == "MATCH"

        untouched = build.scanner_audit(
            store_id,
            aisle_id,
            auditor_id,
            scan_window_start="2026-08-01T12:00:00Z",
            scan_window_end="2026-08-01T13:00:00Z",
            audit_type="FOLLOW_UP",
            actor_headers=auditor_headers,
        )
        assert untouched["status"] == "OPEN"
        scanning = build.read_audit(evidence["audit_id"])
        assert scanning["status"] == "SCANNING"

        validate_error(
            api.create_refund_claim(
                factories.refund_claim_payload(
                    overcharge_line["id"], "CUST-1", scanning["version"]
                ),
                desk_headers,
            ),
            ERR_AUDIT_NOT_CLOSED,
            409,
        )

        validate_error(
            api.close_scanner_audit(untouched["id"], auditor_headers),
            ERR_AUDIT_SAMPLE_EMPTY,
            422,
        )

        closed = build.close_audit(
            evidence["audit_id"], auditor_headers, rate_variant="GROSS_MISMATCH"
        )
        assert closed["status"] == "CLOSED"
        assert_pct(closed["error_rate_pct"], 50.00)
        assert closed["outcome"] == "FAIL"
        closed_version = build.audit_version(evidence["audit_id"])

        validate_error(
            api.create_refund_claim(
                factories.refund_claim_payload(
                    matching_line["id"], "CUST-1", closed_version
                ),
                desk_headers,
            ),
            ERR_NOT_AN_OVERCHARGE,
            422,
        )

        claim_one = validate_success(
            api.create_refund_claim(
                factories.refund_claim_payload(
                    overcharge_line["id"], "CUST-1", closed_version
                ),
                desk_headers,
            ),
            201,
        )
        assert_money_cents(claim_one["claimed_amount_cents"], 199)
        assert claim_one["policy_applied"] == "REFUND_DIFFERENCE_ONLY"
        assert claim_one["status"] == "PENDING"

        validate_error(
            api.create_refund_claim(
                factories.refund_claim_payload(
                    overcharge_line["id"], "CUST-1", closed_version
                ),
                desk_headers,
            ),
            ERR_DUPLICATE_RESOURCE,
            409,
        )

        claim_two = validate_success(
            api.create_refund_claim(
                factories.refund_claim_payload(
                    overcharge_line["id"], "CUST-2", closed_version
                ),
                desk_headers,
            ),
            201,
        )
        assert_money_cents(claim_two["claimed_amount_cents"], 199)

        before = build.read_store(store_id)
        assert_money_cents(before["refund_liability_outstanding_cents"], 398)
        assert_money_cents(before["refund_paid_total_cents"], 0)

        validate_error(
            api.settle_refund_claim(
                claim_one["id"], factories.settle_claim_payload("PAID"), desk_headers
            ),
            ERR_REFUND_NOT_APPROVED,
            409,
        )
        validate_error(
            api.settle_refund_claim(
                claim_two["id"],
                factories.settle_claim_payload("DENIED"),
                manager_headers,
            ),
            ERR_DENIAL_REASON_REQUIRED,
            422,
        )

        approved = build.settle_claim(claim_one["id"], "APPROVED", manager_headers)
        assert approved["status"] == "APPROVED"
        paid = build.settle_claim(claim_one["id"], "PAID", desk_headers)
        assert paid["status"] == "PAID"
        assert_instant_is(paid["paid_at"], "2026-08-01T00:00:00Z")
        validate_error(
            api.settle_refund_claim(
                claim_one["id"], factories.settle_claim_payload("PAID"), desk_headers
            ),
            ERR_TRANSITION_ALREADY_APPLIED,
            409,
        )

        denied = build.settle_claim(
            claim_two["id"],
            "DENIED",
            manager_headers,
            denial_reason="Customer withdrew the complaint",
        )
        assert denied["status"] == "DENIED"
        assert denied["denial_reason"] == "Customer withdrew the complaint"

        after = build.read_store(store_id)
        assert_money_cents(after["refund_liability_outstanding_cents"], 0)
        assert_money_cents(after["refund_paid_total_cents"], 199)

        _rows, meta = validate_paginated(
            api.list_refund_claims(admin_headers, {"store_id": store_id})
        )
        assert meta["total_count"] == 2


class TestRootCauseSegregation:
    def test_the_forbidden_owner_set_is_whoever_closed_the_audits_inside_the_period(
        self, api, build, officer_headers
    ):
        """The same owner id is legal or illegal depending on the period covered.

        PRD 2.9: "**Priority 50 — segregation of duties on remediation.** The
        `remediation_owner_associate_id` assigned to an exception report must not
        be an associate who closed any scanner audit counted in the report's
        period. Failure: `ERR_SEGREGATION_OF_DUTIES` (422). Applies to
        exception-report root-cause assignment."
        PRD 3.9: "The qualifying audits are this store's audits whose status is
        `CLOSED` and whose closing instant falls at or after `period_start_at`
        and strictly before `period_end_at`; audits sitting in `OPEN`,
        `SCANNING` or `REOPENED` are excluded entirely, which means reopening an
        audit removes it from reports generated afterwards."
        PRD 3.9: "Only groups whose sample size is at least 2 are eligible for
        the ranking — a single scan line is anecdote, not evidence."
        PRD 3.9: "When no category is eligible — because the window caught no
        closed audits, or every category had a single line — the report is
        **not** created and the request fails with
        `ERR_NO_QUALIFYING_AUDIT_DATA`."
        PRD 3.9: "Assigning a root cause twice is refused with
        `ERR_EXCEPTION_REPORT_INVALID_STATE`. The named owner must belong to the
        report's own store, failing otherwise with
        `ERR_ASSOCIATE_STORE_MISMATCH`."
        PRD 3.9: "When `root_cause_code` is `TRAINING_GAP`, the assignment
        additionally creates an accountability action against the owner with
        `trigger_code` `EXCEPTION_ROOT_CAUSE`, `action_type`
        `RETRAINING_ASSIGNED` and `issued_by_ref` set to the literal `system`"
        PRD 3.9: "Closing a report still in `GENERATED` is refused with
        `ERR_EXCEPTION_REPORT_INVALID_STATE`."
        PRD 3.9: "When the root cause was `TRAINING_GAP`, closure carries one
        extra precondition: the accountability action created by the assignment
        cascade must have reached `COMPLETED` or `VOIDED`, so a training gap
        cannot be declared closed while the retraining it mandated is still
        outstanding; an action still `ISSUED` blocks the closure with
        `ERR_ACTION_INVALID_STATE`."
        PRD 3.2: "voiding is the compensating operation for the
        accountability-score invariant, and after it the score returns to
        **exactly** its pre-issue value."

        Design: Corner/Validations/corner_root_cause_owner_segregation_depends_on_the_periods_audit_closers
        """
        jurisdiction_id = build.jurisdiction(code="US-CA")
        store_a = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        store_b = build.store(jurisdiction_id, store_number="S002", name="Elm Plaza")
        auditor_id = build.certified(
            store_a,
            ROLE_CODE_PRICE_AUDITOR,
            module_code="AUDIT_101",
            employee_number="E-PA1",
            full_name="Pat Auditor",
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
        auditor_headers = build.auditor(auditor_id)
        aisle_id = build.aisle(store_a, aisle_code="A01", category_code="DAIRY")

        early = build.audit_with_scan_lines(
            store_a,
            aisle_id,
            auditor_id,
            [
                {
                    "item_upc": "00000000013001",
                    "shelf_price_cents": 100,
                    "register_price_cents": 150,
                },
                {
                    "item_upc": "00000000013002",
                    "shelf_price_cents": 100,
                    "register_price_cents": 100,
                },
            ],
            scan_window_start="2026-08-01T08:00:00Z",
            scan_window_end="2026-08-01T09:00:00Z",
        )
        build.set_clock("2026-08-01T09:00:00Z")
        first_closed = build.close_audit(
            early["audit_id"], auditor_headers, rate_variant="GROSS_MISMATCH"
        )
        assert_instant_is(first_closed["closed_at"], "2026-08-01T09:00:00Z")
        assert_pct(first_closed["error_rate_pct"], 50.00)

        late = build.audit_with_scan_lines(
            store_a,
            aisle_id,
            auditor_id,
            [
                {
                    "item_upc": "00000000013003",
                    "shelf_price_cents": 100,
                    "register_price_cents": 150,
                }
            ],
            scan_window_start="2026-08-01T12:00:00Z",
            scan_window_end="2026-08-01T13:00:00Z",
        )
        build.set_clock("2026-08-01T13:30:00Z")
        second_closed = build.close_audit(
            late["audit_id"], auditor_headers, rate_variant="GROSS_MISMATCH"
        )
        assert_instant_is(second_closed["closed_at"], "2026-08-01T13:30:00Z")
        assert second_closed["sample_size"] == 1

        report = validate_success(
            api.create_exception_report(
                factories.exception_report_payload(
                    store_a, "2026-08-01T00:00:00Z", "2026-08-01T12:00:00Z"
                ),
                officer_headers,
            ),
            201,
        )
        assert report["audit_count"] == 1
        assert report["scan_line_count"] == 2
        assert report["top_category_code"] == "DAIRY"
        assert_pct(report["top_category_error_rate_pct"], 50.00)
        assert report["status"] == "GENERATED"

        validate_error(
            api.create_exception_report(
                factories.exception_report_payload(
                    store_a, "2026-08-01T00:00:00Z", "2026-08-01T12:00:00Z"
                ),
                officer_headers,
            ),
            ERR_DUPLICATE_RESOURCE,
            409,
        )
        validate_error(
            api.create_exception_report(
                factories.exception_report_payload(
                    store_a, "2026-08-01T12:00:00Z", "2026-08-01T18:00:00Z"
                ),
                officer_headers,
            ),
            ERR_NO_QUALIFYING_AUDIT_DATA,
            422,
        )

        validate_error(
            api.close_exception_report(
                report["id"], factories.close_report_payload("Premature"), officer_headers
            ),
            ERR_EXCEPTION_REPORT_INVALID_STATE,
            409,
        )

        validate_error(
            api.assign_exception_report_root_cause(
                report["id"],
                factories.root_cause_payload("LABEL_NOT_PLACED", auditor_id),
                officer_headers,
            ),
            ERR_SEGREGATION_OF_DUTIES,
            422,
        )
        validate_error(
            api.assign_exception_report_root_cause(
                report["id"],
                factories.root_cause_payload("LABEL_NOT_PLACED", label_b),
                officer_headers,
            ),
            ERR_ASSOCIATE_STORE_MISMATCH,
            422,
        )

        assigned = validate_success(
            api.assign_exception_report_root_cause(
                report["id"],
                factories.root_cause_payload("TRAINING_GAP", label_a),
                officer_headers,
            )
        )
        assert assigned["status"] == "REMEDIATION_OPEN"
        assert assigned["remediation_owner_associate_id"] == label_a
        assert assigned["root_cause_code"] == "TRAINING_GAP"

        actions, action_meta = validate_paginated(
            api.list_associate_accountability_actions(label_a, officer_headers)
        )
        assert action_meta["total_count"] == 1
        cascade = actions[0]
        assert cascade["trigger_code"] == "EXCEPTION_ROOT_CAUSE"
        assert cascade["action_type"] == "RETRAINING_ASSIGNED"
        assert cascade["issued_by_ref"] == "system"
        assert cascade["status"] == "ISSUED"

        penalised = build.read_associate(label_a)
        assert_pct(penalised["accountability_score"], 90)
        assert penalised["training_status"] == "CERTIFIED"

        validate_error(
            api.assign_exception_report_root_cause(
                report["id"],
                factories.root_cause_payload("TRAINING_GAP", label_a),
                officer_headers,
            ),
            ERR_EXCEPTION_REPORT_INVALID_STATE,
            409,
        )

        validate_error(
            api.close_exception_report(
                report["id"],
                factories.close_report_payload("Retraining delivered"),
                officer_headers,
            ),
            ERR_ACTION_INVALID_STATE,
            409,
        )
        build.void_action(cascade["id"], actor_headers=officer_headers)
        restored = build.read_associate(label_a)
        assert_pct(restored["accountability_score"], 100)

        closed_report = validate_success(
            api.close_exception_report(
                report["id"],
                factories.close_report_payload("Retraining delivered"),
                officer_headers,
            )
        )
        assert closed_report["status"] == "CLOSED"
        assert closed_report["closure_note"] == "Retraining delivered"


class TestEveryCheckSatisfied:
    def test_the_full_cycle_passes_with_every_value_legally_on_its_boundary(
        self, api, build
    ):
        """A pass mark of exactly 80, a resolvable basis and a distinct verifier cost nothing.

        PRD 3.2: "The passing bar is 80 percent."
        PRD 3.3: "The rounded result is stored as `unit_price_display_cents`; the
        basis quantity is stored exactly as computed, never rounded, to as many
        as six fractional digits, as `unit_price_basis_qty`; and the basis label
        is stored as `unit_price_basis_uom`."
        PRD 3.3: "On success, `distributed_at` is stamped with the current
        instant, the unit-price fields of every line that is not `WITHDRAWN` are
        recomputed and re-stored, and the batch's `version` advances by one."
        PRD 3.4: "A newly created task begins with its print axis at
        `NOT_PRINTED`, its placement axis at `UNPLACED`, `printed_label_serial`,
        `placed_by_associate_id`, `verified_by_associate_id`, `placed_at`,
        `verified_at` and `observed_shelf_price_cents` all null, and
        `rejection_count` at 0."
        PRD 3.4: "On success, `placed_by_associate_id` is stamped from
        `X-User-ID` and `placed_at` from the current instant, the store's label
        backlog is recomputed and then its posture recomputed, and when the
        underlying line sits in `FAILED` it moves `FAILED → LABELED`."
        PRD 3.4: "Both outcomes require that the verifying `X-User-ID` differs
        from the task's `placed_by_associate_id`, refusing self-verification with
        `ERR_SEGREGATION_OF_DUTIES`."
        PRD 2.9: "**Priority 59 — verification grace period.** Placement
        verification must happen within 48 hours of the label task's `placed_at`.
        Failure: `ERR_VERIFICATION_WINDOW_CLOSED` (422). Applies to placement
        verification."
        PRD 3.4: "It stamps `verified_by_associate_id` from `X-User-ID` and
        `verified_at` from the current instant, and stores the observed shelf
        price as the verifier's reading. It then advances the underlying line
        `LABELED → VERIFIED` (hop two), which re-derives the batch's
        verified-line count and may complete the batch (hop three), which credits
        `executed_file_count` on every scoped store and re-derives their backlogs
        and postures (hop four)."

        Design: Corner/Validations/corner_every_check_satisfied_lets_the_whole_label_cycle_through_untouched
        """
        jurisdiction_id = build.jurisdiction(
            code="US-CA", unit_price_required=True, grace_period_hours=48
        )
        rulebook = build.read_jurisdiction(jurisdiction_id)
        assert rulebook["unit_price_uom_rule"] == "PER_UNIT_MEASURE_CANONICAL"
        assert rulebook["unit_price_decimal_places"] == 2

        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        assert_posture(build.read_store(store_id), POSTURE_OPEN)

        manager_id = build.certified(
            store_id,
            ROLE_CODE_STORE_MANAGER,
            employee_number="E-SM1",
            full_name="Sam Manager",
        )
        label_id = build.associate(
            store_id,
            ROLE_CODE_LABEL_ASSOCIATE,
            employee_number="E-LA1",
            full_name="Lee Label",
        )
        just_passed = build.train(label_id, "LABEL_101", 80)
        assert just_passed["training_status"] == "CERTIFIED"
        assert_instant_is(
            just_passed["certification_expires_at"], "2027-08-01T00:00:00Z"
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
            assigned_associate_id=label_id,
        )

        draft = build.price_change_file(
            jurisdiction_id, [store_id], file_number="PCF-1"
        )
        assert draft["status"] == "DRAFT"
        line = build.add_line(
            draft["id"],
            item_upc="00000000024001",
            new_retail_cents=448,
            old_retail_cents=499,
            net_content_qty=2,
            net_content_uom="LB",
            item_description="Butter 2 LB",
            category_code="DAIRY",
        )
        assert line["line_status"] == "PENDING"
        assert_money_cents(line["unit_price_display_cents"], 224)
        assert line["unit_price_basis_qty"] == pytest.approx(2, abs=0.000001)
        assert line["unit_price_basis_uom"] == "LB"

        distributed = build.distribute(draft["id"])
        assert distributed["status"] == "DISTRIBUTED"
        assert distributed["version"] == draft["version"] + 1
        assert_instant_is(distributed["distributed_at"], "2026-08-01T00:00:00Z")
        assert distributed["line_count"] == 1

        task = validate_success(
            api.create_label_task(
                draft["id"],
                factories.label_task_payload(
                    store_id,
                    line["id"],
                    aisle_id,
                    label_id,
                    "2026-08-02T08:00:00Z",
                    "2026-08-02T10:00:00Z",
                    distributed["version"],
                ),
                build.manager(manager_id),
            ),
            201,
        )
        assert_instant_is(task["due_at"], "2026-08-05T00:00:00Z")
        assert task["overdue"] is False
        assert task["print_status"] == "NOT_PRINTED"
        assert task["placement_status"] == "UNPLACED"

        printed = build.print_task(task["id"], build.associate_headers(label_id))
        assert printed["print_status"] == "PRINTED"

        placed = build.place_task(task["id"], 448, build.associate_headers(label_id))
        assert placed["placement_status"] == "PLACED"
        assert placed["placed_by_associate_id"] == label_id
        assert_instant_is(placed["placed_at"], "2026-08-01T00:00:00Z")

        verified = build.verify_task(task["id"], build.auditor(auditor_id))
        assert verified["placement_status"] == "VERIFIED"
        assert verified["verified_by_associate_id"] == auditor_id
        assert verified["verified_by_associate_id"] != placed["placed_by_associate_id"]
        assert_instant_is(verified["verified_at"], "2026-08-01T00:00:00Z")
        assert verified["rejection_count"] == 0

        settled_line = build.read_line(line["id"])
        assert settled_line["line_status"] == "VERIFIED"
        assert_money_cents(settled_line["unit_price_display_cents"], 224)

        settled_file = build.read_file(draft["id"])
        assert settled_file["status"] == "EXECUTED"
        assert settled_file["verified_line_count"] == 1
        assert settled_file["version"] > distributed["version"]

        settled_store = build.read_store(store_id)
        assert settled_store["executed_file_count"] == 1
        assert settled_store["label_backlog_count"] == 0
        assert settled_store["open_finding_count"] == 0
        assert_posture(settled_store, POSTURE_OPEN)

        clean = build.read_associate(label_id)
        assert_pct(clean["accountability_score"], 100.00)
        assert clean["issued_action_count"] == 0
        assert clean["training_status"] == "CERTIFIED"
