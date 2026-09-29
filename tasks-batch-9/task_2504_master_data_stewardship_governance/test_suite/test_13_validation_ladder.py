"""The normative order in which a governance request is checked, and the
boundary values of the individual gates it has to pass.

The first group pins the precedence between authentication, authorisation, path
resolution and body checking. The remaining groups sit each admissible request
exactly on its threshold — sixty percent completeness, a due date one instant
too early, a weight budget landing on one hundred points, a clearance rank that
merely equals the domain's classification rank — and check that the inclusive
side is admitted while the exclusive side is refused.
"""

from test_helpers import (
    AUDITOR_HEADERS,
    GOVERNANCE_ADMIN_HEADERS,
    NON_EXISTENT_UUID,
    add_master_record,
    consumer_subscription_payload,
    create_domain,
    headers_without_user_id,
    open_finding,
    quality_rule_payload,
    read_domain,
    set_clock,
    setup_draft_domain,
    setup_governed_domain,
    validate_error,
    validate_paginated,
    validate_success,
)

TWO_FORTY_POINT_RULES = [
    {
        "rule_code": "QR1",
        "dimension": "COMPLETENESS",
        "weight_points": 40,
        "threshold_pct": 90.00,
        "severity": "HIGH",
        "owner": "steward",
    },
    {
        "rule_code": "QR2",
        "dimension": "VALIDITY",
        "weight_points": 40,
        "threshold_pct": 95.00,
        "severity": "MEDIUM",
        "owner": "steward",
    },
]


# --------------------------------------------------------------------------
# Header credibility and the precedence of the early rungs
# --------------------------------------------------------------------------


def test_data_steward_without_a_user_id_header_is_unauthenticated(api):
    """PRD §2.1: "The same error is returned when `X-User-ID` is absent while the acting role is one of the three entity-backed roles — `DataOwner`, `DataSteward`, `ConsumerRep` — because for those roles the identifier is load-bearing rather than decorative."
    PRD §2.9: "Validations are evaluated in the following fifteen-step priority sequence, and the first failure determines the response — later checks are not reached and their errors are never returned in preference to an earlier one."
    PRD §2.9: "1. **Header authentication.** `X-User-Role` present and a declared role, plus `X-User-ID` present for the entity-backed roles. Violation: `ERR_UNAUTHENTICATED` (401). Applies to every endpoint."

    Design: Corner/validations/entity_backed_role_without_user_id_is_unauthenticated
    """
    ctx = setup_draft_domain(rules=[])

    response = api.create_quality_rule(
        quality_rule_payload(ctx["domain"]["id"], ctx["steward"]["id"]),
        headers_without_user_id("DataSteward"),
    )
    validate_error(response, "ERR_UNAUTHENTICATED")

    _, meta = validate_paginated(
        api.list_quality_rules(
            GOVERNANCE_ADMIN_HEADERS, params={"domain_id": ctx["domain"]["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        "an unauthenticated steward must not leave a quality rule behind, got "
        f"{meta['total_count']} rules on the domain"
    )


def test_unauthorised_role_is_refused_before_the_path_domain_is_resolved(api):
    """PRD §2.9: "Validations are evaluated in the following fifteen-step priority sequence, and the first failure determines the response — later checks are not reached and their errors are never returned in preference to an earlier one."
    PRD §2.9: "2. **Endpoint authorisation.** The acting role appears in the endpoint's authorised-role list. Violation: `ERR_UNAUTHORIZED` (403). Applies to every endpoint."
    PRD §2.9: "3. **Path existence.** Every resource named in the path exists, checked left to right, yielding the specific 404 listed above. Applies to every path-parameterised endpoint."
    PRD §2.1: "Once the headers are accepted, the role must additionally appear in the authorised-role list of the endpoint being called (see the table in §4); if it does not, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/validations/role_check_precedes_path_resource_existence
    """
    response = api.activate_domain(NON_EXISTENT_UUID, AUDITOR_HEADERS)

    validate_error(response, "ERR_UNAUTHORIZED")


def test_malformed_body_is_refused_before_a_referenced_steward_is_looked_up(api):
    """PRD §2.9: "Validations are evaluated in the following fifteen-step priority sequence, and the first failure determines the response — later checks are not reached and their errors are never returned in preference to an earlier one."
    PRD §2.9: "4. **Body schema.** Required fields present, enum members valid, numeric ranges respected, array shapes valid — a `measurements` array whose entries each carry `rule_code` and `measured_pct`, a `lineage_path` with at least three entries — and string minimum lengths met. Violation: `ERR_INVALID_REQUEST` (400). Applies to every endpoint that takes a request body."
    PRD §2.9: "5. **Body foreign-key existence.** Every identifier supplied in the request body resolves to an existing row — `domain_id`, `source_system_id`, `steward_id`, `owner_steward_id`, `assigned_steward_id`, `survivor_master_record_id` and `duplicate_master_record_id` — yielding the corresponding 404 (`ERR_DOMAIN_NOT_FOUND`, `ERR_SOURCE_SYSTEM_NOT_FOUND`, `ERR_STEWARD_NOT_FOUND`, `ERR_MASTER_RECORD_NOT_FOUND`). This step guards source-registration creation, steward-assignment creation, quality-rule creation, master-record ingestion, merge-proposal creation, change-request creation, consumer-subscription creation, and remediation planning on a finding."

    Design: Corner/validations/body_schema_check_precedes_body_fk_existence
    """
    ctx = setup_draft_domain(sources=[], rules=[])

    response = api.create_quality_rule(
        quality_rule_payload(
            ctx["domain"]["id"], NON_EXISTENT_UUID, dimension="PUNCTUALITY"
        ),
        ctx["steward_headers"],
    )

    validate_error(response, "ERR_INVALID_REQUEST")


# --------------------------------------------------------------------------
# The publication completeness bar
# --------------------------------------------------------------------------


def _curated_record(api, ctx, natural_key, attributes):
    return add_master_record(
        ctx,
        source_code="ERP",
        curate=True,
        natural_key=natural_key,
        attributes=attributes,
        last_verified_at="2026-08-05T00:00:00Z",
    )


def test_record_at_exactly_sixty_percent_completeness_may_be_published(api):
    """PRD §3.6: "And the record's `completeness_pct` must be at least 60.00, with exactly 60.00 acceptable, otherwise `ERR_RECORD_INCOMPLETE`."
    PRD §3.6: "On success `publication_status` becomes `PUBLISHED`, `published_at` is stamped from the logical clock, the domain's `published_master_record_count` is incremented by one, and the domain's `version` advances by one."
    PRD §3.6: "That count is divided by the domain's `expected_attribute_count`, multiplied by one hundred, and rounded half up to two decimal places; the result is then capped at 100.00, so a record carrying more populated keys than the domain expects reads as exactly complete rather than over-complete."

    Design: Corner/validations/publish_at_exactly_sixty_percent_completeness_is_allowed
    """
    ctx = setup_governed_domain(clock="2026-08-05T00:00:00Z")
    record = _curated_record(
        api,
        ctx,
        "ERP-CUST-60",
        {"legal_name": "Acme Industrial", "tax_id": "TX-77", "billing_city": "Ames"},
    )
    assert record["completeness_pct"] == 60.00, (
        "three of five expected attribute keys must read as exactly 60.00 "
        f"percent complete, got {record['completeness_pct']}"
    )

    published = validate_success(
        api.publish_master_record(record["id"], ctx["steward_headers"])
    )

    assert published["publication_status"] == "PUBLISHED", (
        "completeness exactly on the bar is acceptable, so publication must "
        f"succeed, got publication_status {published['publication_status']}"
    )
    assert published["published_at"] is not None, (
        "a published record carries the instant it went out to consumers, got a "
        "null published_at"
    )

    domain = read_domain(ctx["domain"]["id"])
    assert domain["published_master_record_count"] == 1, (
        "publication increments the domain's published record count, got "
        f"{domain['published_master_record_count']}"
    )


def test_record_below_sixty_percent_completeness_may_not_be_published(api):
    """PRD §3.6: "And the record's `completeness_pct` must be at least 60.00, with exactly 60.00 acceptable, otherwise `ERR_RECORD_INCOMPLETE`."
    PRD §3.6: "On success `publication_status` becomes `PUBLISHED`, `published_at` is stamped from the logical clock, the domain's `published_master_record_count` is incremented by one, and the domain's `version` advances by one."

    Design: Corner/validations/publish_at_exactly_sixty_percent_completeness_is_allowed
    """
    ctx = setup_governed_domain(clock="2026-08-05T00:00:00Z")
    record = _curated_record(
        api, ctx, "ERP-CUST-40", {"legal_name": "Beta Trading", "tax_id": "TX-88"}
    )
    assert record["completeness_pct"] == 40.00, (
        "two of five expected attribute keys must read as 40.00 percent "
        f"complete, got {record['completeness_pct']}"
    )

    response = api.publish_master_record(record["id"], ctx["steward_headers"])
    validate_error(response, "ERR_RECORD_INCOMPLETE")

    domain = read_domain(ctx["domain"]["id"])
    assert domain["published_master_record_count"] == 0, (
        "a refused publication must leave the domain's published record count "
        f"untouched, got {domain['published_master_record_count']}"
    )


# --------------------------------------------------------------------------
# Remediation planning
# --------------------------------------------------------------------------


def test_remediation_assignee_without_an_assignment_on_the_domain_is_refused(api):
    """PRD §3.5: "The nominated assignee must hold an `ACTIVE` `StewardAssignment` on the finding's domain, with a `steward_role` of `DATA_STEWARD`, `CUSTODIAN` or `DATA_OWNER`, whose interval covers the current clock; otherwise the request is rejected with `ERR_ASSIGNMENT_STEWARD_NOT_ELIGIBLE`."
    PRD §3.5: "On success the `assigned_steward_id`, `due_at` and `plan_note` are stored, `planned_by_steward_id` is set to the acting `X-User-ID`, and the assignee's `open_finding_load` is incremented by one."

    Design: Corner/validations/remediation_assignee_must_hold_an_assignment_on_the_domain
    """
    ctx = setup_draft_domain(clock="2026-08-05T00:00:00Z", third_steward=True)
    _, finding = open_finding(ctx, "QR1", 45.00, basis="PROVISIONAL")

    response = api.plan_finding_remediation(
        finding["id"],
        {
            "assigned_steward_id": ctx["third"]["id"],
            "due_at": "2026-08-20T00:00:00Z",
            "plan_note": "Backfill the missing billing attributes",
        },
        ctx["steward_headers"],
    )
    validate_error(response, "ERR_ASSIGNMENT_STEWARD_NOT_ELIGIBLE")

    outsider = validate_success(
        api.get_steward(ctx["third"]["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert outsider["open_finding_load"] == 0, (
        "a steward with no assignment on the domain must not be charged with the "
        f"finding, got open_finding_load {outsider['open_finding_load']}"
    )


def test_remediation_assignee_holding_the_data_steward_seat_is_accepted(api):
    """PRD §3.5: "The nominated assignee must hold an `ACTIVE` `StewardAssignment` on the finding's domain, with a `steward_role` of `DATA_STEWARD`, `CUSTODIAN` or `DATA_OWNER`, whose interval covers the current clock; otherwise the request is rejected with `ERR_ASSIGNMENT_STEWARD_NOT_ELIGIBLE`."
    PRD §3.5: "Planning a remediation drives the finding `OPEN → REMEDIATION_PLANNED`."
    PRD §3.5: "On success the `assigned_steward_id`, `due_at` and `plan_note` are stored, `planned_by_steward_id` is set to the acting `X-User-ID`, and the assignee's `open_finding_load` is incremented by one."

    Design: Corner/validations/remediation_assignee_must_hold_an_assignment_on_the_domain
    """
    ctx = setup_draft_domain(clock="2026-08-05T00:00:00Z", third_steward=True)
    _, finding = open_finding(ctx, "QR1", 45.00, basis="PROVISIONAL")

    planned = validate_success(
        api.plan_finding_remediation(
            finding["id"],
            {
                "assigned_steward_id": ctx["steward"]["id"],
                "due_at": "2026-08-20T00:00:00Z",
                "plan_note": "Backfill the missing billing attributes",
            },
            ctx["steward_headers"],
        )
    )

    assert planned["status"] == "REMEDIATION_PLANNED", (
        "the accountable data steward is an eligible assignee, so the finding "
        f"must move to REMEDIATION_PLANNED, got {planned['status']}"
    )
    assert planned["assigned_steward_id"] == ctx["steward"]["id"], (
        "the nominated assignee must be recorded on the finding, got "
        f"{planned['assigned_steward_id']}"
    )

    charged = validate_success(
        api.get_steward(ctx["steward"]["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert charged["open_finding_load"] == 1, (
        "the assignee's remediation load must rise by one, got "
        f"{charged['open_finding_load']}"
    )


def test_remediation_due_at_equal_to_the_clock_is_refused(api):
    """PRD §3.5: "And `due_at` must fall strictly after the current logical clock — a due date equal to the clock is not acceptable — otherwise `ERR_DUE_DATE_IN_PAST`."
    PRD §3.5: "Planning a remediation drives the finding `OPEN → REMEDIATION_PLANNED`."
    PRD §3.5: "On success the `assigned_steward_id`, `due_at` and `plan_note` are stored, `planned_by_steward_id` is set to the acting `X-User-ID`, and the assignee's `open_finding_load` is incremented by one."

    Design: Corner/validations/remediation_due_at_equal_to_the_clock_is_rejected
    """
    ctx = setup_draft_domain(clock="2026-08-05T00:00:00Z")
    _, finding = open_finding(ctx, "QR1", 45.00, basis="PROVISIONAL")

    response = api.plan_finding_remediation(
        finding["id"],
        {
            "assigned_steward_id": ctx["steward"]["id"],
            "due_at": "2026-08-05T00:00:00Z",
            "plan_note": "Same-instant deadline",
        },
        ctx["steward_headers"],
    )
    validate_error(response, "ERR_DUE_DATE_IN_PAST")

    unchanged = validate_success(
        api.get_quality_finding(finding["id"], ctx["steward_headers"])
    )
    assert unchanged["status"] == "OPEN", (
        "a deadline landing exactly on the clock leaves the finding open, got "
        f"status {unchanged['status']}"
    )

    steward = validate_success(
        api.get_steward(ctx["steward"]["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert steward["open_finding_load"] == 0, (
        "the refused plan must charge nobody's remediation load, got "
        f"{steward['open_finding_load']}"
    )


# --------------------------------------------------------------------------
# The hundred-point scorecard budget
# --------------------------------------------------------------------------


def test_new_rule_pushing_the_weight_budget_past_one_hundred_is_refused(api):
    """PRD §3.3: "The scorecard is a fixed budget of one hundred points per domain. Summing `weight_points` across all of the domain's `ACTIVE` rules — including the rule being created, or including the new value of a rule being modified — must yield at most 100; exceeding it is `ERR_RULE_WEIGHT_BUDGET_EXCEEDED`."
    PRD §2.9: "15. **Scorecard weight budget.** The sum of `weight_points` over the domain's `ACTIVE` quality rules, counting the incoming or updated rule, must not exceed 100. Violation: `ERR_RULE_WEIGHT_BUDGET_EXCEEDED` (422). This step guards quality-rule creation and quality-rule modification."

    Design: Corner/validations/active_rule_weight_budget_is_an_aggregate_ceiling
    """
    ctx = setup_draft_domain(rules=TWO_FORTY_POINT_RULES)

    response = api.create_quality_rule(
        quality_rule_payload(
            ctx["domain"]["id"],
            ctx["steward"]["id"],
            rule_code="QR3",
            dimension="TIMELINESS",
            weight_points=30,
            threshold_pct=80.00,
            severity="LOW",
        ),
        ctx["steward_headers"],
    )

    validate_error(response, "ERR_RULE_WEIGHT_BUDGET_EXCEEDED")


def test_weight_revision_is_re_checked_against_the_budget_with_its_new_value(api):
    """PRD §3.3: "The scorecard is a fixed budget of one hundred points per domain. Summing `weight_points` across all of the domain's `ACTIVE` rules — including the rule being created, or including the new value of a rule being modified — must yield at most 100; exceeding it is `ERR_RULE_WEIGHT_BUDGET_EXCEEDED`."
    PRD §2.9: "15. **Scorecard weight budget.** The sum of `weight_points` over the domain's `ACTIVE` quality rules, counting the incoming or updated rule, must not exceed 100. Violation: `ERR_RULE_WEIGHT_BUDGET_EXCEEDED` (422). This step guards quality-rule creation and quality-rule modification."
    PRD §3.3: "Rules are created in `status` `ACTIVE` and enter the scorecard denominator from the next run onward."

    Design: Corner/validations/active_rule_weight_budget_is_an_aggregate_ceiling
    """
    ctx = setup_draft_domain(rules=TWO_FORTY_POINT_RULES)

    third = validate_success(
        api.create_quality_rule(
            quality_rule_payload(
                ctx["domain"]["id"],
                ctx["steward"]["id"],
                rule_code="QR3",
                dimension="TIMELINESS",
                weight_points=20,
                threshold_pct=80.00,
                severity="LOW",
            ),
            ctx["steward_headers"],
        ),
        201,
    )
    assert third["weight_points"] == 20, (
        "a third rule landing the budget on exactly one hundred points is "
        f"admissible, got weight_points {third['weight_points']}"
    )
    assert third["status"] == "ACTIVE", (
        f"a newly created rule is active, got status {third['status']}"
    )

    response = api.update_quality_rule(
        third["id"], {"weight_points": 21}, ctx["steward_headers"]
    )
    validate_error(response, "ERR_RULE_WEIGHT_BUDGET_EXCEEDED")


# --------------------------------------------------------------------------
# Ownership of a critical rule
# --------------------------------------------------------------------------


def test_senior_steward_may_own_a_high_rule_but_not_a_critical_one(api):
    """PRD §3.3: "Only a `PRINCIPAL`-certified steward may own a `CRITICAL`-severity rule: naming an owner whose `certification_level` is `JUNIOR` or `SENIOR` on a `CRITICAL` rule is rejected with `ERR_OWNER_NOT_PRINCIPAL`."
    PRD §3.3: "Rules are created in `status` `ACTIVE` and enter the scorecard denominator from the next run onward."

    Design: Corner/validations/critical_severity_rule_requires_a_principal_owner
    """
    ctx = setup_draft_domain(rules=[])

    high = validate_success(
        api.create_quality_rule(
            quality_rule_payload(
                ctx["domain"]["id"],
                ctx["steward"]["id"],
                rule_code="QR_HIGH",
                dimension="COMPLETENESS",
                weight_points=30,
                threshold_pct=90.00,
                severity="HIGH",
            ),
            ctx["steward_headers"],
        ),
        201,
    )
    assert high["status"] == "ACTIVE", (
        "a senior steward may own a high-severity rule, got status "
        f"{high['status']}"
    )

    response = api.create_quality_rule(
        quality_rule_payload(
            ctx["domain"]["id"],
            ctx["steward"]["id"],
            rule_code="QR_CRIT",
            dimension="VALIDITY",
            weight_points=30,
            threshold_pct=95.00,
            severity="CRITICAL",
        ),
        ctx["steward_headers"],
    )
    validate_error(response, "ERR_OWNER_NOT_PRINCIPAL")


def test_critical_rule_owned_by_a_principal_steward_is_accepted(api):
    """PRD §3.3: "Only a `PRINCIPAL`-certified steward may own a `CRITICAL`-severity rule: naming an owner whose `certification_level` is `JUNIOR` or `SENIOR` on a `CRITICAL` rule is rejected with `ERR_OWNER_NOT_PRINCIPAL`."
    PRD §3.3: "A steward defines one by naming the `domain_id` it scores, the `owner_steward_id` accountable for it and its findings, a `rule_code` of 1 to 20 characters that must be unique within the domain (`ERR_DUPLICATE_RULE_CODE` otherwise), the `dimension` measured — one of `COMPLETENESS`, `VALIDITY`, `UNIQUENESS`, `TIMELINESS` or `CONSISTENCY` — a `weight_points` value between 1 and 100 expressing the rule's share of the scorecard, a `threshold_pct` between 0.00 and 100.00 carried to two decimal places, and a `severity` of `LOW`, `MEDIUM`, `HIGH` or `CRITICAL` that determines how heavily a breach of the rule weighs on the domain."
    PRD §3.3: "Rules are created in `status` `ACTIVE` and enter the scorecard denominator from the next run onward."

    Design: Corner/validations/critical_severity_rule_requires_a_principal_owner
    """
    ctx = setup_draft_domain(rules=[])

    refused = api.create_quality_rule(
        quality_rule_payload(
            ctx["domain"]["id"],
            ctx["steward"]["id"],
            rule_code="QR_CRIT",
            dimension="VALIDITY",
            weight_points=30,
            threshold_pct=95.00,
            severity="CRITICAL",
        ),
        ctx["steward_headers"],
    )
    validate_error(refused, "ERR_OWNER_NOT_PRINCIPAL")

    accepted = validate_success(
        api.create_quality_rule(
            quality_rule_payload(
                ctx["domain"]["id"],
                ctx["owner"]["id"],
                rule_code="QR_CRIT",
                dimension="VALIDITY",
                weight_points=30,
                threshold_pct=95.00,
                severity="CRITICAL",
            ),
            ctx["steward_headers"],
        ),
        201,
    )

    assert accepted["owner_steward_id"] == ctx["owner"]["id"], (
        "the principal steward must be recorded as the critical rule's owner, "
        f"got {accepted['owner_steward_id']}"
    )
    assert accepted["status"] == "ACTIVE", (
        f"a newly created rule is active, got status {accepted['status']}"
    )


# --------------------------------------------------------------------------
# The consumer clearance bar
# --------------------------------------------------------------------------


def _confidential_vendor_domain():
    set_clock("2026-08-01T00:00:00Z")
    return create_domain(
        code="VENDOR", name="Vendor Master", classification_level="CONFIDENTIAL"
    )


def test_consumer_cleared_below_the_domain_classification_is_refused(api):
    """PRD §2.10: "A consumer may only be registered against a domain if its clearance rank is greater than or equal to the domain's classification rank; equality is acceptable."
    PRD §3.9: "Registration enforces the clearance bar of §2.10: a subscription may only be created when its `clearance_level` rank is greater than or equal to the domain's `classification_level` rank, and a shortfall is rejected with `ERR_CLEARANCE_INSUFFICIENT`."
    PRD §2.10: "The boolean `sensitive_handling_required` is derived, never supplied: it is true exactly when the domain's `classification_level` is `CONFIDENTIAL` or `RESTRICTED`, and false for `PUBLIC` and `INTERNAL`."

    Design: Corner/validations/consumer_clearance_below_domain_classification_is_refused
    """
    domain = _confidential_vendor_domain()
    assert domain["sensitive_handling_required"] is True, (
        "a confidential domain requires sensitive handling, got "
        f"{domain['sensitive_handling_required']}"
    )

    response = api.create_consumer_subscription(
        consumer_subscription_payload(
            domain["id"],
            consumer_code="BI_LOW",
            reporting_asset_key="RPT_LOW",
            clearance_level="INTERNAL",
            criticality="TIER2",
            required_lead_days=5,
        ),
        GOVERNANCE_ADMIN_HEADERS,
    )

    validate_error(response, "ERR_CLEARANCE_INSUFFICIENT")


def test_consumer_cleared_above_the_domain_classification_is_admitted(api):
    """PRD §2.10: "A consumer may only be registered against a domain if its clearance rank is greater than or equal to the domain's classification rank; equality is acceptable."
    PRD §2.10: "Those four values form a strict rank ordering in which `PUBLIC` is rank 1, `INTERNAL` is rank 2, `CONFIDENTIAL` is rank 3 and `RESTRICTED` is rank 4, and every clearance comparison in the system is a comparison of those ranks."
    PRD §3.9: "A new subscription begins with `status` `ACTIVE` and `lineage_status` `UNDOCUMENTED`, an empty `lineage_path`, and `lineage_revision`, `lineage_documented_at`, `pending_change_request_id`, `notified_at`, `acknowledged_at`, `acknowledged_revision` and `suspended_reason` all null."

    Design: Corner/validations/consumer_clearance_below_domain_classification_is_refused
    """
    domain = _confidential_vendor_domain()

    subscription = validate_success(
        api.create_consumer_subscription(
            consumer_subscription_payload(
                domain["id"],
                consumer_code="BI_HIGH",
                reporting_asset_key="RPT_HIGH",
                clearance_level="RESTRICTED",
                criticality="TIER2",
                required_lead_days=5,
            ),
            GOVERNANCE_ADMIN_HEADERS,
        ),
        201,
    )

    assert subscription["status"] == "ACTIVE", (
        "a consumer cleared above the domain's classification is admitted "
        f"active, got status {subscription['status']}"
    )
    assert subscription["clearance_level"] == "RESTRICTED", (
        "the subscription must carry the clearance it was registered with, got "
        f"{subscription['clearance_level']}"
    )
    assert subscription["lineage_status"] == "UNDOCUMENTED", (
        "a brand new subscription has no documented lineage yet, got "
        f"{subscription['lineage_status']}"
    )
