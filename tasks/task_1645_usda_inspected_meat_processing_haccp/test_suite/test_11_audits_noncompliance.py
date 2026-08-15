"""Humane-handling audits, noncompliance records, appeal/resolve workflow."""
from test_helpers import (
    INSPECTOR_1,
    INSPECTOR_2,
    TEST_USERS,
    ApiErrorId,
    appeal_payload,
    humane_audit_payload,
    resolve_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures

ADMIN = TEST_USERS["plant_admin_headers"]
QA = TEST_USERS["qa_manager_headers"]
PROD = TEST_USERS["production_manager_headers"]


class TestHumaneAuditFailureCascade:
    def test_failed_audit_creates_nr_suspends_plant_and_day(self, api):
        """PRD §3.9: "A `FAILED` outcome fires the noncompliance cascade of §2.8: a `NoncomplianceRecord` is created for the plant with `category` `HUMANE_HANDLING`, severity `CRITICAL`, `created_by` set to the auditor, a server-defaulted `regulation_cite` appropriate to the category, a server-generated narrative `description`, and the audited day linked through `production_day_id`; the audit's `noncompliance_record_id` points at it (and stays null when the audit passed)."
        PRD §3.9: "The plant's `operating_status` flips to `SUSPENDED`, and every `OPEN` production day of the plant suspends with it."

        Design: Difficulty/transitive_cascade/humane_audit_failure_nr_suspension_cascade
        """
        env = fixtures.setup_open_day(
            establishment_number="EST-1645-H1", process_type="SLAUGHTER",
            ccp_overrides={"ccp_code": "CCP-1S", "description": "Scald water",
                           "critical_limit_min_f": 140.0,
                           "critical_limit_max_f": None},
        )
        audit = fixtures.create_humane_audit(
            env["plant"]["id"], env["day"]["id"], auditor_id=INSPECTOR_1,
            stunning_efficacy_pct=98.5, slips_falls_pct=2.0, vocalization_pct=5.0,
        )
        assert audit["outcome"] == "FAILED", "98.5 is below the 99.0 threshold"
        nr_id = audit.get("noncompliance_record_id")
        assert nr_id, "a FAILED audit links its NoncomplianceRecord"

        nr = validate_success(api.get_noncompliance_record(nr_id, QA), 200)
        assert nr["category"] == "HUMANE_HANDLING"
        assert nr["severity"] == "CRITICAL"
        assert nr["status"] == "OPEN"
        assert nr["created_by"] == INSPECTOR_1
        assert nr["production_day_id"] == env["day"]["id"]

        plant = validate_success(api.get_plant(env["plant"]["id"], QA), 200)
        assert plant["operating_status"] == "SUSPENDED"

        day = validate_success(api.get_production_day(env["day"]["id"], QA), 200)
        assert day["status"] == "SUSPENDED"

    def test_failed_audit_suspends_every_open_day(self, api):
        """PRD §3.9: "The plant's `operating_status` flips to `SUSPENDED`, and every `OPEN` production day of the plant suspends with it."
        PRD §3.9: "The inspector's `X-User-ID` is recorded as `auditor_user_id`."

        Design: Difficulty/transitive_cascade/humane_audit_failure_nr_suspension_cascade
        """
        env = fixtures.setup_open_day(
            establishment_number="EST-1645-H2", process_type="SLAUGHTER",
            ccp_overrides={"ccp_code": "CCP-1S", "description": "Scald water",
                           "critical_limit_min_f": 140.0,
                           "critical_limit_max_f": None},
            shift_end="2026-08-02T18:00:00Z",
        )
        # A second day opens on the following date.
        day2 = fixtures.plan_production_day(
            env["plant"]["id"], production_date="2026-08-02",
            process_type="SLAUGHTER",
        )
        fixtures.set_clock("2026-08-02T07:00:00Z")
        fixtures.open_day(day2["id"])

        audit = fixtures.create_humane_audit(
            env["plant"]["id"], env["day"]["id"], auditor_id=INSPECTOR_1,
            stunning_efficacy_pct=98.5, slips_falls_pct=2.0, vocalization_pct=5.0,
        )
        assert audit["outcome"] == "FAILED"
        assert audit["auditor_user_id"] == INSPECTOR_1
        assert audit["production_day_id"] == env["day"]["id"]

        day1_after = validate_success(
            api.get_production_day(env["day"]["id"], QA), 200
        )
        day2_after = validate_success(api.get_production_day(day2["id"], QA), 200)
        assert day1_after["status"] == "SUSPENDED"
        assert day2_after["status"] == "SUSPENDED", (
            "every OPEN day of the plant suspends with the plant"
        )
        plant = validate_success(api.get_plant(env["plant"]["id"], QA), 200)
        assert plant["operating_status"] == "SUSPENDED"


class TestHumaneAuditThresholds:
    def test_audit_at_exact_thresholds_passes(self, api):
        """PRD §3.9: "The `outcome` is computed synchronously at creation, comparing the inputs exactly as provided: `PASSED` when stunning efficacy is at least 99.0 and slips and falls are at most 3.0 and vocalization is at most 10.0, and `FAILED` otherwise."
        PRD §3.9: "A `FAILED` outcome fires the noncompliance cascade of §2.8: a `NoncomplianceRecord` is created for the plant with `category` `HUMANE_HANDLING`, severity `CRITICAL`, `created_by` set to the auditor, a server-defaulted `regulation_cite` appropriate to the category, a server-generated narrative `description`, and the audited day linked through `production_day_id`; the audit's `noncompliance_record_id` points at it (and stays null when the audit passed)."

        Design: Corner/calculations/humane_audit_exact_thresholds_pass
        """
        env = fixtures.setup_open_day(
            establishment_number="EST-1645-22", process_type="SLAUGHTER",
            ccp_overrides={"ccp_code": "CCP-1S", "description": "Scald water",
                           "critical_limit_min_f": 140.0,
                           "critical_limit_max_f": None},
        )
        audit = fixtures.create_humane_audit(
            env["plant"]["id"], env["day"]["id"], auditor_id=INSPECTOR_1,
            stunning_efficacy_pct=99.0, slips_falls_pct=3.0, vocalization_pct=10.0,
        )
        assert audit["outcome"] == "PASSED", "all three thresholds are inclusive"
        assert audit.get("noncompliance_record_id") is None

        records, meta = validate_paginated(
            api.list_noncompliance_records(QA, params={"plant_id": env["plant"]["id"]})
        )
        assert records == [], "a PASSED audit creates no noncompliance record"
        assert meta["total_count"] == 0

        plant = validate_success(api.get_plant(env["plant"]["id"], QA), 200)
        assert plant["operating_status"] == "ACTIVE"


class TestNoncomplianceRecordWorkflow:
    def test_appeal_after_close_returns_noncompliance_invalid_state(self, api):
        """PRD §3.9: "A `QAManager` appeals an `OPEN` record — any other state draws `ERR_NONCOMPLIANCE_INVALID_STATE` — recording the payload's `appeal_note` and moving it to `APPEALED`."

        Design: Corner/state_machines/nr_appeal_after_close_returns_noncompliance_invalid_state
        """
        env, _audit, nr_id = fixtures.setup_suspended_plant_via_humane_failure(
            establishment_number="EST-1645-07"
        )
        resolved = validate_success(
            api.resolve_noncompliance_record(
                nr_id, resolve_payload(
                    resolution_note="Stun operator retrained; verified"),
                fixtures.make_inspector_headers(INSPECTOR_2),
            ),
            200,
        )
        assert resolved["status"] == "CLOSED"

        resp = api.appeal_noncompliance_record(nr_id, appeal_payload(), QA)
        validate_error(resp, ApiErrorId.ERR_NONCOMPLIANCE_INVALID_STATE)
        assert resp.status_code == 409

        after = validate_success(api.get_noncompliance_record(nr_id, QA), 200)
        assert after["status"] == "CLOSED"

    def test_resolve_by_creator_returns_segregation_error(self, api):
        """PRD §3.9: "An `Inspector` resolves a record from `OPEN` or `APPEALED` by supplying a `resolution_note`; after the state check, segregation of duties requires the resolver's `X-User-ID` to differ from the record's `created_by`, otherwise `ERR_SEGREGATION_OF_DUTIES_VIOLATION`."
        PRD §3.9: "Resolution stamps `resolved_by`, moves the record to `CLOSED`, and recomputes the plant's `operating_status`: when the closed record was the plant's last `OPEN` `CRITICAL` record, the plant returns from `SUSPENDED` to `ACTIVE`, while days suspended along the way stay suspended until explicitly reopened."

        Design: Corner/validations/nr_resolve_by_creator_returns_segregation_error
        """
        env, _audit, nr_id = fixtures.setup_suspended_plant_via_humane_failure(
            establishment_number="EST-1645-33"
        )
        # The auditor whose FAILED audit created the record may not close it.
        by_creator = api.resolve_noncompliance_record(
            nr_id, resolve_payload(resolution_note="Self-resolution attempt"),
            fixtures.make_inspector_headers(INSPECTOR_1),
        )
        validate_error(by_creator, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)
        assert by_creator.status_code == 403

        by_other = validate_success(
            api.resolve_noncompliance_record(
                nr_id, resolve_payload(
                    resolution_note="Corrective action verified on site"),
                fixtures.make_inspector_headers(INSPECTOR_2),
            ),
            200,
        )
        assert by_other["status"] == "CLOSED"
        assert by_other["resolved_by"] == INSPECTOR_2

        plant = validate_success(api.get_plant(env["plant"]["id"], ADMIN), 200)
        assert plant["operating_status"] == "ACTIVE", (
            "closing the last OPEN CRITICAL record reactivates the plant"
        )
        day = validate_success(api.get_production_day(env["day"]["id"], PROD), 200)
        assert day["status"] == "SUSPENDED", (
            "days suspended along the way stay suspended until reopened"
        )
