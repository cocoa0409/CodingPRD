"""Engagement registration, jurisdiction registry rows and declared defaults."""

from test_helpers import (
    AUDITOR_HEADERS,
    COMPLIANCE_ANALYST_HEADERS,
    ClassificationStatus,
    DutiesTestVariant,
    DutiesValidationStatus,
    IcTest,
    LookbackPolicy,
    PROGRAM_ADMIN_HEADERS,
    ProjectStatus,
    RemediationPosture,
    TriggerReasonCode,
    TriggerType,
    assert_bare_uuid,
    assert_has_system_fields,
    assert_iso_timestamp,
    assert_money,
    assert_no_optimistic_lock_fields,
    assert_project_ledgers,
    factories,
    fixtures,
    validate_paginated,
    validate_success,
)


def test_engagement_creation_returns_declared_defaults_and_version_one(api, pinned_clock):
    """A brand new engagement lands in PLANNING with an OPEN posture and empty ledgers.

    PRD: "Most resources additionally carry `updated_at` -- an ISO 8601 UTC timestamp, same
    format, refreshed on every mutation -- and `version`, an integer that starts at 1 on
    creation and increments by one on every mutation of that row."

    Design: Corner/entities/audit_project_creation_returns_declared_defaults_and_version_one
    """
    response = api.create_audit_project(
        factories.audit_project_payload(
            name="FY26 Classification Audit",
            fiscal_year=2026,
            lookback_policy=LookbackPolicy.STANDARD_2Y,
        ),
        PROGRAM_ADMIN_HEADERS,
    )
    project = validate_success(response, 201)

    assert project["status"] == ProjectStatus.PLANNING, (
        f"a new engagement must start in PLANNING, got {project['status']}"
    )
    assert_project_ledgers(
        project,
        headcount=0,
        exposure_cents=0,
        payroll_delta_cents=0,
        committed_correction_cents=0,
        posture=RemediationPosture.OPEN,
    )
    assert_has_system_fields(project, "engagement")
    assert project["version"] == 1, f"version must start at 1, got {project['version']}"
    assert_bare_uuid(project["id"], "engagement.id")
    assert_iso_timestamp(project["created_at"], "engagement.created_at")
    assert_iso_timestamp(project["updated_at"], "engagement.updated_at")


def test_engagement_retrieval_returns_the_stored_row_unchanged(api, pinned_clock):
    """Reading an engagement back is a pure read that neither mutates nor recomputes it.

    PRD: "Recomputing a derived field counts as a mutation: when an interview attestation
    rewrites a position's validated duty percentage, that position's `updated_at` is refreshed
    and its `version` is incremented, even though no client sent a request naming the position."

    Design: Corner/entities/audit_project_retrieval_returns_the_stored_row_unchanged
    """
    created = validate_success(
        api.create_audit_project(
            factories.audit_project_payload(
                name="FY26 Classification Audit",
                fiscal_year=2026,
                lookback_policy=LookbackPolicy.WILLFUL_3Y,
            ),
            PROGRAM_ADMIN_HEADERS,
        ),
        201,
    )

    fetched = validate_success(api.get_audit_project(created["id"], AUDITOR_HEADERS), 200)

    assert fetched["id"] == created["id"], "the read must return the same row"
    assert fetched["name"] == "FY26 Classification Audit", "name must survive the round trip"
    assert fetched["fiscal_year"] == 2026, "fiscal_year must survive the round trip"
    assert fetched["lookback_policy"] == LookbackPolicy.WILLFUL_3Y, (
        f"lookback_policy expected WILLFUL_3Y, got {fetched['lookback_policy']}"
    )
    assert fetched["status"] == ProjectStatus.PLANNING, "a pure read must not advance the stage"
    assert fetched["version"] == 1, (
        f"a pure read must not bump the version, got {fetched['version']}"
    )


def test_engagement_system_fields_are_server_minted_and_client_input_ignored(api, pinned_clock):
    """Client-supplied id, status and version values are discarded in favour of server values.

    PRD: "Every resource the API mints carries an `id` that is a server-generated UUID with no
    type prefix, and a `created_at` that is an ISO 8601 UTC timestamp with three fractional
    digits (for example `2026-08-01T00:00:00.000Z`)."

    Design: Corner/entities/audit_project_system_fields_are_server_minted_and_input_ignored
    """
    smuggled_id = "11111111-1111-4111-8111-111111111111"
    project = validate_success(
        api.create_audit_project(
            factories.audit_project_payload(
                id=smuggled_id, status=ProjectStatus.CLOSED, version=99
            ),
            PROGRAM_ADMIN_HEADERS,
        ),
        201,
    )

    assert project["id"] != smuggled_id, "the server must mint its own id"
    assert_bare_uuid(project["id"], "engagement.id")
    assert project["status"] == ProjectStatus.PLANNING, (
        f"client-supplied status must be ignored, got {project['status']}"
    )
    assert project["version"] == 1, (
        f"client-supplied version must be ignored, got {project['version']}"
    )
    assert_iso_timestamp(project["created_at"], "engagement.created_at")
    assert project["created_at"] == project["updated_at"], (
        "a freshly created row has never been mutated, so the two stamps must match"
    )


def test_jurisdiction_rule_is_immutable_and_omits_the_lock_fields(api, pinned_clock):
    """A jurisdiction rule is configuration: it carries no version and no updated_at.

    PRD: "A **jurisdiction rule** (`StateRule`) is configuration. It is immutable once created
    and keyed by `state_code`."

    Design: Corner/entities/state_rule_is_immutable_with_no_version_field_and_no_update_endpoint
    """
    rule = validate_success(
        api.create_state_rule(
            factories.state_rule_payload(
                "NY",
                min_weekly_salary_cents=124000,
                duties_test_variant=DutiesTestVariant.STRICT_ENUM,
                ic_test=IcTest.COMMON_LAW,
                computer_exemption_recognized=False,
                hce_shortcut_recognized=False,
                liquidated_damages_multiplier=2.0,
                reclass_notice_days=21,
                back_wage_lookback_weeks_override=312,
            ),
            PROGRAM_ADMIN_HEADERS,
        ),
        201,
    )

    assert_no_optimistic_lock_fields(rule, "jurisdiction rule")
    assert rule["state_code"] == "NY", "state_code must be echoed back"
    assert_money(rule["min_weekly_salary_cents"], 124000, "min_weekly_salary_cents")
    assert_money(rule["hce_annual_cents"], 0, "hce_annual_cents default")
    assert rule["outside_sales_recognized"] is True, (
        f"outside_sales_recognized must default to true, got {rule['outside_sales_recognized']}"
    )
    assert rule["computer_exemption_recognized"] is False, (
        f"computer_exemption_recognized expected false, got {rule['computer_exemption_recognized']}"
    )
    assert rule["liquidated_damages_multiplier"] == 2.0, (
        f"liquidated_damages_multiplier expected 2.0, got {rule['liquidated_damages_multiplier']}"
    )
    assert rule["back_wage_lookback_weeks_override"] == 312, (
        "back_wage_lookback_weeks_override must be echoed back, got "
        f"{rule['back_wage_lookback_weeks_override']}"
    )

    rows, meta = validate_paginated(api.list_state_rules(AUDITOR_HEADERS))
    assert meta["total_count"] == 1, f"exactly one rule was registered, got {meta['total_count']}"
    assert len(rows) == 1, f"listing must return the single rule, got {len(rows)}"
    assert_no_optimistic_lock_fields(rows[0], "listed jurisdiction rule")


def test_job_change_trigger_rows_are_append_only_audit_records(api, ca_engagement):
    """Two triggers on one job both persist as immutable log rows that wrote no attribute.

    PRD: "A **job change trigger** (`JobChangeTrigger`) is an append-only event log row. It is
    never mutated after creation."

    Design: Corner/entities/job_change_trigger_rows_are_append_only_audit_records
    """
    position_id = ca_engagement["position_id"]

    first = validate_success(
        api.create_job_change_trigger(
            factories.job_change_trigger_payload(
                position_id,
                trigger_type=TriggerType.SALARY_CHANGE,
                new_annual_salary_cents=6000000,
            ),
            COMPLIANCE_ANALYST_HEADERS,
        ),
        201,
    )
    second = validate_success(
        api.create_job_change_trigger(
            factories.job_change_trigger_payload(
                position_id,
                trigger_type=TriggerType.SALARY_CHANGE,
                new_annual_salary_cents=6500000,
            ),
            COMPLIANCE_ANALYST_HEADERS,
        ),
        201,
    )

    assert first["id"] != second["id"], "each trigger is a distinct log row"
    for label, trigger in (("first", first), ("second", second)):
        assert_no_optimistic_lock_fields(trigger, f"{label} trigger")
        assert trigger["requires_reanalysis"] is False, (
            f"{label} trigger must not require reanalysis, got {trigger['requires_reanalysis']}"
        )
        assert trigger["reason_code"] == TriggerReasonCode.NO_REANALYSIS_REQUIRED, (
            f"{label} reason_code expected NO_REANALYSIS_REQUIRED, got {trigger['reason_code']}"
        )

    position = fixtures.read_position(api, position_id)
    assert_money(position["annual_salary_cents"], 5500000, "annual_salary_cents")

    rows, meta = validate_paginated(
        api.list_position_job_change_triggers(position_id, COMPLIANCE_ANALYST_HEADERS)
    )
    assert meta["total_count"] == 2, f"both trigger rows must persist, got {meta['total_count']}"
    assert len(rows) == 2, f"listing must return both trigger rows, got {len(rows)}"


def test_position_optional_flags_default_to_false_when_omitted(api, ca_planning_engagement):
    """Omitting the two optional qualifiers materializes false rather than null.

    PRD: "Two optional booleans complete the picture and both default to `false`:
    `requires_advanced_degree`, meaning the job requires a prolonged course of specialized
    intellectual instruction, and `works_primarily_offsite`, meaning the incumbent customarily
    works away from the employer's place of business."

    Design: Corner/entities/position_create_omitting_optional_flags_defaults_them_to_false
    """
    position = validate_success(
        api.create_position(
            factories.position_payload(
                ca_planning_engagement["family_id"], title="Line Lead", job_code="LL-110"
            ),
            PROGRAM_ADMIN_HEADERS,
        ),
        201,
    )

    assert position["requires_advanced_degree"] is False, (
        f"requires_advanced_degree must default to false, got {position['requires_advanced_degree']}"
    )
    assert position["works_primarily_offsite"] is False, (
        f"works_primarily_offsite must default to false, got {position['works_primarily_offsite']}"
    )
    assert position["duties_validation_status"] == DutiesValidationStatus.PENDING, (
        f"a new job starts with PENDING duties, got {position['duties_validation_status']}"
    )
    assert position["classification_status"] == ClassificationStatus.UNREVIEWED, (
        f"a new job starts UNREVIEWED, got {position['classification_status']}"
    )
    assert position["overtime_eligible"] is False, (
        "an EXEMPT job is not overtime eligible, got "
        f"{position['overtime_eligible']}"
    )
    assert position["self_reported_exempt_pct_override"] is None, (
        "the duty override starts null, got "
        f"{position['self_reported_exempt_pct_override']!r}"
    )


def test_position_weekly_salary_is_recomputed_and_client_values_ignored(api, ca_planning_engagement):
    """Derived salary, duty and status fields are computed, never accepted from the client.

    PRD: "Creating a position immediately derives `weekly_salary_cents` as the annual salary
    divided by 52 and truncated to a whole cent"

    Design: Corner/entities/position_weekly_salary_is_recomputed_and_client_supplied_value_input_ignored
    """
    position = validate_success(
        api.create_position(
            factories.position_payload(
                ca_planning_engagement["family_id"],
                title="Assistant Manager",
                job_code="AM-120",
                annual_salary_cents=5500000,
                weekly_salary_cents=999999,
                primary_duty_pct=95.0,
                classification_status=ClassificationStatus.RECLASSIFIED,
            ),
            PROGRAM_ADMIN_HEADERS,
        ),
        201,
    )

    assert_money(position["annual_salary_cents"], 5500000, "annual_salary_cents")
    assert_money(position["weekly_salary_cents"], 105769, "weekly_salary_cents")
    assert position["primary_duty_pct"] == 0.0, (
        f"client-supplied primary_duty_pct must be ignored, got {position['primary_duty_pct']}"
    )
    assert position["classification_status"] == ClassificationStatus.UNREVIEWED, (
        "client-supplied classification_status must be ignored, got "
        f"{position['classification_status']}"
    )
    assert position["validated_weekly_hours"] == 47, (
        "validated_weekly_hours must fall back to the employer-stated average, got "
        f"{position['validated_weekly_hours']}"
    )
