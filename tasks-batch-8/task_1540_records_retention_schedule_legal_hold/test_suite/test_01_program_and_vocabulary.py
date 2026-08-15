"""Governance program configuration defaults and controlled-vocabulary rules."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_governance_program,
    create_custodian_payload,
    create_jurisdiction_payload,
    create_program,
    create_program_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
RM = TEST_USERS["records_manager_headers"]
AUD = TEST_USERS["auditor_headers"]


class TestProgramDefaults:
    def test_program_create_applies_config_defaults(self, api):
        """PRD §3.1: "Five operational parameters may optionally be overridden
        at creation; when omitted they take their defaults. `ack_deadline_days`
        defaults to 14 and must be greater than 0"
        PRD §3.1: "`reminder_interval_days` defaults to 7 and must be greater
        than 0"
        PRD §3.1: "`max_reminders_before_escalation` defaults to 3 and must be
        at least 1"
        PRD §3.1: "`stale_hold_days` defaults to 180 and must be greater than 0"
        PRD §3.1: "`over_preservation_warn_pct` defaults to 20"
        PRD §3.1: "`ack_sla_mode` selects between `STRICT` and
        `REMINDER_ADJUSTED` and defaults to `STRICT`"
        PRD §2.4: "`version` starts at 1 on creation and increments by 1 on
        every mutation of the entity"

        Design: Corner/entities/program_create_applies_config_defaults
        """
        resp = api.create_program(
            create_program_payload(name="Defaults", fiscal_year_end_month=12,
                                   fiscal_year_end_day=31),
            ADMIN,
        )
        program = validate_success(resp, 201)
        assert_governance_program(program)
        assert program["ack_deadline_days"] == 14
        assert program["reminder_interval_days"] == 7
        assert program["max_reminders_before_escalation"] == 3
        assert program["stale_hold_days"] == 180
        assert program["over_preservation_warn_pct"] == 20
        assert program["ack_sla_mode"] == "STRICT"
        assert program["version"] == 1, "version starts at 1 on creation"

        reread = validate_success(api.get_program(program["id"], AUD), 200)
        assert reread["ack_deadline_days"] == 14, "defaults persist on re-read"
        assert reread["ack_sla_mode"] == "STRICT"
        assert reread["version"] == 1


class TestControlledVocabularies:
    def test_create_record_class_missing_required_returns_invalid_request(self, api):
        """PRD §3.1: "Each record class carries `code` (unique within its
        program), `name`, and `monthly_storage_cost_cents_per_gb` (a
        fractional-cents storage rate per GB-month, strictly greater than 0,
        used by over-preservation costing)."
        PRD §2.8: "a missing required field, type mismatch, or numeric range
        violation (such as `retention_months` not greater than 0, `size_gb` not
        greater than 0, `ack_deadline_days` not greater than 0,
        `monthly_storage_cost_cents_per_gb` not greater than 0,
        `fiscal_year_end_month` outside 1–12, or a `fiscal_year_end_day`
        invalid for its month) is rejected with `ERR_INVALID_REQUEST` (HTTP
        400)"

        Design: Corner/entities/create_record_class_missing_required_returns_invalid_request
        """
        program = create_program(name="P")
        resp = api.create_record_class(
            {"program_id": program["id"], "code": "BROKEN", "name": "No rate"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        _data, meta = validate_paginated(api.list_record_classes(ADMIN))
        assert meta["total_count"] == 0, "The rejected create persisted nothing"

    def test_jurisdiction_code_unique_per_program_only(self, api):
        """PRD §3.1: "Each jurisdiction carries `code` (unique within its
        program) and `name`. Reusing an existing code within the same program
        is rejected with `ERR_DUPLICATE_CODE` (HTTP 409)."

        Design: Corner/entities/jurisdiction_code_unique_per_program_only
        """
        p1 = create_program(name="P1")
        p2 = create_program(name="P2")
        first = validate_success(api.create_jurisdiction(
            create_jurisdiction_payload(p1["id"], code="US-FED", name="Federal"),
            ADMIN), 201)
        assert first["code"] == "US-FED"

        dup = api.create_jurisdiction(
            create_jurisdiction_payload(p1["id"], code="US-FED", name="Duplicate"),
            ADMIN)
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_CODE)

        other = api.create_jurisdiction(
            create_jurisdiction_payload(p2["id"], code="US-FED", name="Federal P2"),
            ADMIN)
        reused = validate_success(other, 201)
        assert reused["program_id"] == p2["id"], (
            "Uniqueness is program-scoped: the same code is reusable in another program"
        )

    def test_custodian_email_unique_per_program(self, api):
        """PRD §3.1: "A `RecordsManager` registers custodians with `email`
        (unique within its program — duplicates yield `ERR_DUPLICATE_CUSTODIAN`),
        `full_name`, and `department`."

        Design: Corner/entities/custodian_email_unique_per_program
        """
        program = create_program(name="P")
        first = validate_success(api.create_custodian(
            create_custodian_payload(program["id"], email="c@x.com",
                                     full_name="First"),
            RM), 201)
        assert first["open_obligation_count"] == 0, (
            "A freshly registered custodian's open_obligation_count starts at 0"
        )

        dup = api.create_custodian(
            create_custodian_payload(program["id"], email="c@x.com",
                                     full_name="Second", department="HR"),
            RM)
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_CUSTODIAN)

        _data, meta = validate_paginated(api.list_custodians(RM))
        assert meta["total_count"] == 1, "Only the first custodian exists"
