"""Data dictionary entries, worker hiring, assignment-row seeding, position creation."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_data_field,
    create_data_field_payload,
    create_position_record,
    create_worker_payload,
    get_success_data,
    is_iso8601_timestamp,
    validate_error,
    validate_success,
)


class TestDataFieldCreation:
    def test_create_data_field_defaults_and_activate(self, api, steward_headers):
        """PRD §3.1: "A `DataSteward` creates a data field by supplying its
        `field_key`, a `display_name`, a `sensitivity`, a `history_policy`, an
        `owner_team`, and optionally `downstream_channels`."
        PRD §3.1: "The `downstream_channels` list is a subset of `PAYROLL`,
        `BENEFITS`, and `IDENTITY`, defaults to empty, and determines how many
        integration events a successful apply emits — one per channel."
        PRD §3.1: "A new field starts in `DRAFT`. A `DataSteward` activates it,
        moving `DRAFT` to `ACTIVE`; activation or deprecation attempted from the
        wrong state is rejected with `ERR_FIELD_NOT_ACTIVE`."

        Design: Corner/entities/create_data_field_defaults_and_activate
        """
        payload = create_data_field_payload(
            field_key="assignment.pay_grade", display_name="Pay Grade",
            sensitivity="INTERNAL", history_policy="CORRECTABLE", owner_team="people",
        )
        assert "downstream_channels" not in payload
        resp = api.create_data_field(payload, steward_headers)
        created = validate_success(resp, expected_status=201)
        assert created["status"] == "DRAFT"
        assert created["downstream_channels"] == []
        assert_data_field(created)

        activated = validate_success(api.activate_data_field(created["id"], steward_headers))
        assert activated["status"] == "ACTIVE"
        reread = validate_success(api.get_data_field(created["id"], steward_headers))
        assert reread["status"] == "ACTIVE"

    def test_create_data_field_missing_required_field_key_rejected(self, api, steward_headers):
        """PRD §2.8: "missing required fields, unparseable enum, date or integer
        values, an unknown `field_key`, a duplicate `worker_number` or `field_key`,
        a `termination_date` earlier than the hire date, or a `valid_until` earlier
        than `valid_from` are rejected with `ERR_INVALID_REQUEST` (400)."
        PRD §3.1: "A `DataSteward` creates a data field by supplying its
        `field_key`, a `display_name`, a `sensitivity`, a `history_policy`, an
        `owner_team`, and optionally `downstream_channels`."

        Design: Corner/entities/create_data_field_missing_required_field_key_rejected
        """
        first = create_data_field_payload(field_key="assignment.salary_cents")
        validate_success(api.create_data_field(first, steward_headers), expected_status=201)

        payload = create_data_field_payload(display_name="No Key")
        payload.pop("field_key")
        resp = api.create_data_field(payload, steward_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_data_field_invalid_sensitivity_enum_rejected(self, api, steward_headers):
        """PRD §3.1: "The `sensitivity` is one of `PUBLIC`, `INTERNAL`,
        `CONFIDENTIAL`, or `RESTRICTED`, and `RESTRICTED` forces dual approval
        later in the change lifecycle."
        PRD §2.8: "missing required fields, unparseable enum, date or integer
        values, an unknown `field_key`, a duplicate `worker_number` or `field_key`,
        a `termination_date` earlier than the hire date, or a `valid_until` earlier
        than `valid_from` are rejected with `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/create_data_field_invalid_sensitivity_enum_rejected
        """
        payload = create_data_field_payload(
            field_key="assignment.pay_grade", sensitivity="TOP_SECRET",
        )
        resp = api.create_data_field(payload, steward_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_data_field_unknown_field_key_rejected(self, api, steward_headers):
        """PRD §3.1: "The `field_key` must name one of the seven governable
        attributes — `assignment.position_id`, `assignment.salary_cents`,
        `assignment.pay_grade`, `assignment.location_code`,
        `position.parent_position_id`, `position.title`, or `position.department`
        — and must be unique across the dictionary; an unknown key or a duplicate
        is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_data_field_unknown_field_key_rejected
        """
        payload = create_data_field_payload(field_key="assignment.foo", display_name="Bogus")
        resp = api.create_data_field(payload, steward_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_data_field_duplicate_field_key_rejected(self, api, steward_headers):
        """PRD §3.1: "The `field_key` must name one of the seven governable
        attributes — `assignment.position_id`, `assignment.salary_cents`,
        `assignment.pay_grade`, `assignment.location_code`,
        `position.parent_position_id`, `position.title`, or `position.department`
        — and must be unique across the dictionary; an unknown key or a duplicate
        is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_data_field_duplicate_field_key_rejected
        """
        first = create_data_field_payload(field_key="assignment.salary_cents")
        validate_success(api.create_data_field(first, steward_headers), expected_status=201)

        dup = create_data_field_payload(
            field_key="assignment.salary_cents", display_name="Salary Duplicate",
            sensitivity="CONFIDENTIAL", history_policy="APPEND_ONLY",
        )
        resp = api.create_data_field(dup, steward_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestWorkerHiring:
    def test_create_worker_duplicate_worker_number_rejected(self, api, analyst_headers):
        """PRD §3.3: "The `worker_number` must be unique and the salary
        non-negative; violations surface as `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_worker_duplicate_worker_number_rejected
        """
        pos = create_position_record()
        first = create_worker_payload(
            legal_name="First", worker_number="W600", initial_position_id=pos["id"],
        )
        validate_success(api.create_worker(first, analyst_headers), expected_status=201)

        dup = create_worker_payload(
            legal_name="Second", worker_number="W600", hire_date="2026-02-01",
            initial_position_id=pos["id"], initial_salary_cents=11000,
        )
        resp = api.create_worker(dup, analyst_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_worker_seeds_initial_assignment_row(self, api, analyst_headers):
        """PRD §3.3: "Hiring does two things at once: the worker record is created
        `ACTIVE` with `version` 1 and a null `termination_date`, and the first
        assignment row is seeded from the hire — spanning the open-ended interval
        starting at `hire_date`, stamped with the initial position, salary, pay
        grade, and location, and carrying a null `change_request_id` to mark it as
        the origin row rather than a change product."
        PRD §3.3: "That row's `row_status` is `ACTIVE` when the hire date is on or
        before the logical clock date and `FUTURE` otherwise."

        Design: Corner/entities/create_worker_seeds_initial_assignment_row
        """
        pos = create_position_record()
        payload = create_worker_payload(
            legal_name="Seed Row", worker_number="W700", hire_date="2026-01-05",
            initial_position_id=pos["id"], initial_salary_cents=10000,
            initial_pay_grade="G7", initial_location_code="NY",
        )
        worker = validate_success(api.create_worker(payload, analyst_headers), expected_status=201)
        assert worker["status"] == "ACTIVE"

        resp = api.list_position_assignments(analyst_headers, params={"worker_id": worker["id"]})
        rows = get_success_data(resp)
        assert len(rows) == 1, f"expected exactly one seeded row, got {len(rows)}"
        row = rows[0]
        assert row["effective_start_date"] == "2026-01-05"
        assert row["effective_end_date"] is None
        assert row["salary_cents"] == 10000
        assert row["pay_grade"] == "G7"
        assert row["location_code"] == "NY"
        assert row["change_request_id"] is None
        assert row["row_status"] == "ACTIVE"

    def test_create_worker_future_hire_row_status_future(self, api, analyst_headers):
        """PRD §3.3: "That row's `row_status` is `ACTIVE` when the hire date is on
        or before the logical clock date and `FUTURE` otherwise."
        PRD §2.5: "At startup, before any operator intervention, the clock reads
        exactly 2026-08-01T00:00:00Z — never the wall clock."

        Design: Corner/entities/create_worker_future_hire_row_status_future
        """
        pos = create_position_record()
        payload = create_worker_payload(
            legal_name="Future Hire", worker_number="W701", hire_date="2026-09-01",
            initial_position_id=pos["id"], initial_salary_cents=10000,
        )
        worker = validate_success(api.create_worker(payload, analyst_headers), expected_status=201)
        assert worker["status"] == "ACTIVE"

        resp = api.list_position_assignments(analyst_headers, params={"worker_id": worker["id"]})
        rows = get_success_data(resp)
        assert len(rows) == 1
        assert rows[0]["row_status"] == "FUTURE"

    def test_worker_create_position_fk_not_found(self, api, analyst_headers):
        """PRD §2.9: "Requests targeting nested resources resolve path identifiers
        sequentially, left to right, and the request is rejected immediately with
        the 404 error corresponding to the first identifier that does not resolve."
        PRD §2.8: "3. **Existence** — path identifiers are resolved left to
        right, and body foreign keys such as `target_field_id`, `target_row_id`,
        `initial_position_id`, and `parent_position_id` must exist (the
        resource-specific not-found errors, 404; see §2.9)."

        Design: Corner/entities/worker_create_position_fk_not_found
        """
        create_position_record()  # DB non-empty
        payload = create_worker_payload(
            legal_name="No Pos", worker_number="W712",
            initial_position_id=NON_EXISTENT_UUID,
        )
        resp = api.create_worker(payload, analyst_headers)
        validate_error(resp, ApiErrorId.ERR_POSITION_NOT_FOUND)


class TestDataFieldStateMachine:
    def test_data_field_deprecate_state_guards(self, api, steward_headers):
        """PRD §3.1: "A new field starts in `DRAFT`. A `DataSteward` activates it,
        moving `DRAFT` to `ACTIVE`; activation or deprecation attempted from the
        wrong state is rejected with `ERR_FIELD_NOT_ACTIVE`."
        PRD §3.1: "Deprecation moves `ACTIVE` to `DEPRECATED`, after which any new
        change request or batch line referencing the field is rejected with
        `ERR_FIELD_NOT_ACTIVE`, while requests already in flight —
        `PENDING_APPROVAL`, `PARTIALLY_APPROVED`, or `APPROVED` — are unaffected."

        Design: Corner/state_machines/data_field_deprecate_state_guards
        """
        payload = create_data_field_payload(field_key="assignment.pay_grade", display_name="Grade")
        field = validate_success(api.create_data_field(payload, steward_headers), expected_status=201)

        err1 = api.deprecate_data_field(field["id"], steward_headers)
        validate_error(err1, ApiErrorId.ERR_FIELD_NOT_ACTIVE)

        validate_success(api.activate_data_field(field["id"], steward_headers))
        deprecated = validate_success(api.deprecate_data_field(field["id"], steward_headers))
        assert deprecated["status"] == "DEPRECATED"

        err2 = api.deprecate_data_field(field["id"], steward_headers)
        validate_error(err2, ApiErrorId.ERR_FIELD_NOT_ACTIVE)

    def test_activate_active_field_rejected(self, api, steward_headers):
        """PRD §3.1: "A new field starts in `DRAFT`. A `DataSteward` activates it,
        moving `DRAFT` to `ACTIVE`; activation or deprecation attempted from the
        wrong state is rejected with `ERR_FIELD_NOT_ACTIVE`."

        Design: Corner/state_machines/activate_active_field_rejected
        """
        payload = create_data_field_payload(field_key="assignment.location_code", display_name="Location")
        field = validate_success(api.create_data_field(payload, steward_headers), expected_status=201)
        validate_success(api.activate_data_field(field["id"], steward_headers))

        err = api.activate_data_field(field["id"], steward_headers)
        validate_error(err, ApiErrorId.ERR_FIELD_NOT_ACTIVE)

        reread = validate_success(api.get_data_field(field["id"], steward_headers))
        assert reread["status"] == "ACTIVE"
