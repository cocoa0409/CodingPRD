"""The criteria catalog, the control set, the criteria-mapping graph, and the two
coverage views computed over them."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approve_control_design,
    assert_control,
    assert_coverage_ordering,
    assert_trust_criterion,
    assign_owner,
    create_control,
    create_criterion,
    create_engagement,
    create_manual_gap,
    lead_engagement_action,
    map_control,
    read_control,
    read_engagement,
    read_readiness_summary,
    setup_approved_locked_description,
    validate_error,
    validate_paginated,
    validate_success,
)

CL_HEADERS = TEST_USERS["compliance_lead_headers"]
AUD_HEADERS = TEST_USERS["auditor_headers"]
PA_HEADERS = TEST_USERS["platform_admin_headers"]

FIVE_CRITERIA = [
    {"criterion_code": "CC1.1", "category": "SECURITY", "title": "Control environment"},
    {"criterion_code": "CC6.1", "category": "SECURITY", "title": "Logical access"},
    {"criterion_code": "A1.1", "category": "AVAILABILITY", "title": "Capacity management"},
    {"criterion_code": "A1.2", "category": "AVAILABILITY", "title": "Backup and recovery"},
    {"criterion_code": "C1.1", "category": "CONFIDENTIALITY", "title": "Confidential data handling"},
]


def build_two_view_scenario():
    """Five in-scope criteria across three categories; K-01 is DESIGN_APPROVED with an
    ACTIVE PRIMARY mapping to CC1.1 and K-02 is only DESIGN_MAPPED with an ACTIVE
    SECONDARY mapping to A1.1. Nothing is TESTED_EFFECTIVE."""
    criteria = {}
    for spec in FIVE_CRITERIA:
        row = create_criterion(
            criterion_code=spec["criterion_code"],
            category=spec["category"],
            title=spec["title"],
            min_primary_controls=1,
            applies_to_report_types=("SOC_2_TYPE_2",),
        )
        criteria[spec["criterion_code"]] = row

    engagement = create_engagement(
        client_name="Northwind",
        report_type="SOC_2_TYPE_2",
        categories=("SECURITY", "AVAILABILITY", "CONFIDENTIALITY"),
        max_distribution_recipients=5,
    )
    setup_approved_locked_description(engagement["id"])

    k01 = create_control(
        engagement["id"],
        control_ref="K-01",
        title="Quarterly access review",
        frequency="MONTHLY",
        automation="MANUAL",
        risk_rating="HIGH",
        population_size=40,
    )
    k02 = create_control(
        engagement["id"],
        control_ref="K-02",
        title="Capacity trending",
        frequency="QUARTERLY",
        automation="MANUAL",
        risk_rating="MODERATE",
        population_size=12,
    )
    map_control(k01["id"], criteria["CC1.1"]["id"], mapping_type="PRIMARY",
                rationale="Primary coverage of CC1.1")
    map_control(k02["id"], criteria["A1.1"]["id"], mapping_type="SECONDARY",
                rationale="Supporting coverage of A1.1")
    assign_owner(k01["id"], "own-1")
    lead_engagement_action(engagement["id"], "START_READINESS")
    approve_control_design(k01["id"])

    return {
        "engagement_id": engagement["id"],
        "criteria": criteria,
        "controls": {"K-01": k01, "K-02": k02},
    }


def test_control_read_back_matches_the_row_that_was_created(api):
    """PRD 3.3: "Each control names its `engagement_id`, a `control_ref` label of 1 to 40
    characters unique within the engagement — which doubles as the deterministic sort key
    of the readiness assessment in §3.5 — and a `title` of 1 to 200 characters."
    PRD 3.3: "The required `frequency` is one of `DAILY`, `WEEKLY`, `MONTHLY`,
    `QUARTERLY`, `ANNUAL` or `ADHOC` and drives both the evidence calendar and the
    sampling base."

    Design: Corner/entities/corner_get_control_by_id_returns_stored_row
    """
    engagement = create_engagement(client_name="Readback")
    control = create_control(
        engagement["id"],
        control_ref="R-01",
        title="Weekly scan",
        frequency="WEEKLY",
        automation="AUTOMATED",
        risk_rating="HIGH",
        population_size=30,
    )

    data = validate_success(api.get_control(control["id"], AUD_HEADERS), 200)
    assert_control(data)
    assert data["control_ref"] == "R-01"
    assert data["frequency"] == "WEEKLY"
    assert data["automation"] == "AUTOMATED"
    assert data["risk_rating"] == "HIGH"
    assert data["population_size"] == 30
    assert data["engagement_id"] == engagement["id"]


def test_control_without_a_frequency_is_rejected(api):
    """PRD 3.3: "The required `frequency` is one of `DAILY`, `WEEKLY`, `MONTHLY`,
    `QUARTERLY`, `ANNUAL` or `ADHOC` and drives both the evidence calendar and the
    sampling base."
    PRD 2.7: "Every required input field present, every value of the declared type, every
    enumerated value a declared member, every count field at least 0, and every ordering
    constraint between a period start and its end, or between a coverage start and an
    as-of instant, satisfied. Otherwise `ERR_VALIDATION` (422)."

    Design: Corner/entities/corner_create_control_missing_required_frequency_returns_validation
    """
    engagement = create_engagement(client_name="Missing Fields")

    response = api.create_control(
        {"engagement_id": engagement["id"], "control_ref": "M-01", "title": "No frequency"},
        CL_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 422)

    _, meta = validate_paginated(
        api.list_controls(CL_HEADERS, params={"engagement_id": engagement["id"]})
    )
    assert meta["total_count"] == 0, "A rejected create must store no control"


def test_catalog_criterion_carries_no_version_and_no_updated_at(api):
    """PRD 2.4: "The single exception is the trust services criteria catalog: a
    `TrustCriterion` row carries only `id` and `created_at`. It has no `updated_at` and no
    `version`, because catalog entries are never mutated after creation."
    PRD 3.3: "`min_primary_controls` defaults to 1, must be at least 1, and states how
    many primary mappings a criterion needs before the attestation view will treat it as
    covered."
    PRD 3.3: "Catalog rows are immutable once written, which is why, as §2.4 notes, they
    carry no `updated_at` and no `version`."

    Design: Corner/entities/corner_trust_criterion_is_immutable_config_without_version
    """
    response = api.create_trust_criterion(
        {
            "criterion_code": "CC1.1",
            "category": "SECURITY",
            "title": "Control environment",
            "min_primary_controls": 2,
            "applies_to_report_types": ["SOC_1_TYPE_2", "SOC_2_TYPE_2"],
        },
        PA_HEADERS,
    )
    data = validate_success(response, 201)
    assert_trust_criterion(data)
    assert "version" not in data, "A catalog row must expose no version field"
    assert "updated_at" not in data, "A catalog row must expose no updated_at field"
    assert data["min_primary_controls"] == 2
    assert data["applies_to_report_types"] == ["SOC_1_TYPE_2", "SOC_2_TYPE_2"]


def test_mapping_rows_are_reachable_from_the_control_and_from_the_criterion(api):
    """PRD 3.3: "A `ComplianceLead` supplies `control_id` and `trust_criterion_id`, plus
    an optional `mapping_type` that defaults to `PRIMARY` and may instead be `SECONDARY`,
    and an optional free-text `rationale`."
    PRD 3.3: "The new mapping's `status` is `ACTIVE` and its `retired_at` is null.
    Creating it recomputes the control's `active_mapping_count` and
    `primary_mapping_count`; when `active_mapping_count` rises from 0 to 1 on an in-scope
    control, the control moves `DESIGN_DRAFT → DESIGN_MAPPED`."

    Design: Corner/entities/corner_many_to_many_junction_is_reachable_from_both_sides
    """
    criterion = create_criterion("CC1.1")
    engagement = create_engagement(client_name="Junction")
    first = create_control(engagement["id"], control_ref="K-01", title="Access provisioning")
    second = create_control(
        engagement["id"], control_ref="K-02", title="Access review", frequency="QUARTERLY"
    )

    primary = validate_success(
        api.create_criteria_mapping(
            {
                "control_id": first["id"],
                "trust_criterion_id": criterion["id"],
                "mapping_type": "PRIMARY",
            },
            CL_HEADERS,
        ),
        201,
    )
    secondary = validate_success(
        api.create_criteria_mapping(
            {
                "control_id": second["id"],
                "trust_criterion_id": criterion["id"],
                "mapping_type": "SECONDARY",
            },
            CL_HEADERS,
        ),
        201,
    )

    by_control, control_meta = validate_paginated(
        api.list_criteria_mappings(CL_HEADERS, params={"control_id": first["id"]})
    )
    assert control_meta["total_count"] == 1
    assert by_control[0]["id"] == primary["id"]

    _, criterion_meta = validate_paginated(
        api.list_criteria_mappings(CL_HEADERS, params={"trust_criterion_id": criterion["id"]})
    )
    assert criterion_meta["total_count"] == 2

    assert primary["status"] == "ACTIVE"
    assert secondary["mapping_type"] == "SECONDARY"
    assert read_control(first["id"])["design_status"] == "DESIGN_MAPPED"
    second_after = read_control(second["id"])
    assert second_after["design_status"] == "DESIGN_MAPPED"
    assert second_after["primary_mapping_count"] == 0
    assert second_after["active_mapping_count"] == 1


def test_retiring_the_only_mapping_returns_the_control_to_design_draft(api):
    """PRD 3.3: "Retiring a mapping is a soft delete: the row survives with `status`
    `RETIRED` and `retired_at` stamped from the logical clock, remains readable and
    listable, and stops participating in every coverage view."
    PRD 3.3: "It recomputes the control's two mapping counters, moves the control
    `DESIGN_MAPPED → DESIGN_DRAFT` when `active_mapping_count` falls to 0, and recomputes
    both coverage counts, both percentages and `readiness_score`."

    Design: Corner/state_machines/corner_criteria_mapping_delete_reverts_control_to_design_draft
    """
    criterion = create_criterion("CC1.1")
    engagement = create_engagement(client_name="Unmap")
    control = create_control(engagement["id"], control_ref="K-01", title="Access provisioning")
    mapping = map_control(control["id"], criterion["id"], mapping_type="PRIMARY")

    retired = validate_success(api.retire_criteria_mapping(mapping["id"], CL_HEADERS), 200)
    assert retired["status"] == "RETIRED"
    assert retired["retired_at"] is not None, "retired_at must be stamped on retirement"

    reread = validate_success(api.get_criteria_mapping(mapping["id"], CL_HEADERS), 200)
    assert reread["status"] == "RETIRED", "The retired row remains readable"

    control_after = read_control(control["id"])
    assert control_after["active_mapping_count"] == 0
    assert control_after["primary_mapping_count"] == 0
    assert control_after["design_status"] == "DESIGN_DRAFT"

    engagement_after = read_engagement(engagement["id"])
    assert engagement_after["covered_criteria_count_readiness"] == 0
    assert engagement_after["criteria_coverage_pct_readiness"] == 0.00


def test_control_ref_is_unique_per_engagement_only(api):
    """PRD 3.3: "Each control names its `engagement_id`, a `control_ref` label of 1 to 40
    characters unique within the engagement — which doubles as the deterministic sort key
    of the readiness assessment in §3.5 — and a `title` of 1 to 200 characters."
    PRD 2.7: "**Uniqueness**, else `ERR_DUPLICATE_RESOURCE` (409)."

    Design: Corner/validations/corner_duplicate_control_ref_within_engagement_rejected
    """
    first_engagement = create_engagement(client_name="First")
    second_engagement = create_engagement(client_name="Second")
    create_control(first_engagement["id"], control_ref="K-01", title="Access provisioning")

    duplicate = api.create_control(
        {
            "engagement_id": first_engagement["id"],
            "control_ref": "K-01",
            "title": "Duplicate reference",
            "frequency": "QUARTERLY",
        },
        CL_HEADERS,
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_RESOURCE.value, 409)

    _, meta = validate_paginated(
        api.list_controls(CL_HEADERS, params={"engagement_id": first_engagement["id"]})
    )
    assert meta["total_count"] == 1

    elsewhere = validate_success(
        api.create_control(
            {
                "engagement_id": second_engagement["id"],
                "control_ref": "K-01",
                "title": "Same ref, other engagement",
                "frequency": "QUARTERLY",
            },
            CL_HEADERS,
        ),
        201,
    )
    assert elsewhere["control_ref"] == "K-01"
    assert elsewhere["engagement_id"] == second_engagement["id"]


def test_criterion_code_is_unique_across_the_whole_catalog(api):
    """PRD 3.3: "A catalog entry carries a `criterion_code` of 1 to 20 uppercase
    characters that must be globally unique — a repeat is `ERR_DUPLICATE_RESOURCE` — a
    `category` drawn from the same five values an engagement may require, and a `title` of
    1 to 200 characters."

    Design: Corner/validations/corner_duplicate_criterion_code_is_globally_rejected
    """
    first = create_criterion("CC1.1", category="SECURITY", title="Control environment")

    duplicate = api.create_trust_criterion(
        {
            "criterion_code": "CC1.1",
            "category": "AVAILABILITY",
            "title": "Different title",
            "min_primary_controls": 1,
            "applies_to_report_types": ["SOC_2_TYPE_2"],
        },
        PA_HEADERS,
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_RESOURCE.value, 409)

    _, meta = validate_paginated(api.list_trust_criteria(PA_HEADERS))
    assert meta["total_count"] == 1
    assert validate_success(api.get_trust_criterion(first["id"], PA_HEADERS))["category"] == "SECURITY"


def test_criterion_whose_report_types_omit_the_engagement_is_out_of_scope(api):
    """PRD 3.3: "`applies_to_report_types` defaults to an array containing only
    `SOC_2_TYPE_2`, must be non-empty, and may contain `SOC_1_TYPE_2`, `SOC_2_TYPE_2` or
    both; a criterion whose array omits an engagement's `report_type` is never in scope
    for that engagement."
    PRD 3.3: "The referenced control must have `in_scope` true and a `design_status` other
    than `DESIGN_CARVED_OUT`, else `ERR_CONTROL_OUT_OF_SCOPE`; the referenced criterion
    must be in scope for the engagement, else `ERR_CRITERION_OUT_OF_SCOPE`; and the pair
    of `control_id` and `trust_criterion_id` must not already exist among that control's
    active mappings, else `ERR_DUPLICATE_RESOURCE`."

    Design: Corner/validations/corner_criterion_out_of_scope_for_report_type_rejected
    """
    criterion = create_criterion(
        "CC9.9",
        category="SECURITY",
        title="Financial reporting controls",
        applies_to_report_types=("SOC_1_TYPE_2",),
    )
    engagement = create_engagement(client_name="Mismatch", report_type="SOC_2_TYPE_2")
    control = create_control(engagement["id"], control_ref="K-01", title="Access provisioning")

    response = api.create_criteria_mapping(
        {
            "control_id": control["id"],
            "trust_criterion_id": criterion["id"],
            "mapping_type": "PRIMARY",
        },
        CL_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_CRITERION_OUT_OF_SCOPE.value, 409)

    assert read_engagement(engagement["id"])["criteria_in_scope_count"] == 0
    assert read_control(control["id"])["design_status"] == "DESIGN_DRAFT"
    _, meta = validate_paginated(
        api.list_criteria_mappings(CL_HEADERS, params={"control_id": control["id"]})
    )
    assert meta["total_count"] == 0


def test_assign_owner_only_sets_the_owner_and_bumps_the_version(api):
    """PRD 3.4: "A `ComplianceLead` assigns one by supplying `owner_user_id`, the opaque
    operator identifier of the `ControlOwner` who will submit that control's evidence.
    Assignment sets the field and moves neither state dimension."
    PRD 2.4: "Most resources additionally carry `updated_at`, refreshed on every mutation
    of that row, and `version`, an integer that starts at 1 when the row is created and
    increases by exactly one on every mutation."

    Design: Corner/endpoints/corner_assign_owner_action_touches_only_owner_and_version
    """
    engagement = create_engagement(client_name="Ownership")
    control = create_control(engagement["id"], control_ref="K-01", title="Access provisioning")
    assert control["version"] == 1

    first = validate_success(
        api.assign_control_owner(control["id"], {"owner_user_id": "own-1"}, CL_HEADERS)
    )
    assert first["owner_user_id"] == "own-1"
    assert first["version"] == 2

    second = validate_success(
        api.assign_control_owner(control["id"], {"owner_user_id": "own-2"}, CL_HEADERS)
    )
    assert second["owner_user_id"] == "own-2", "Re-assignment overwrites rather than errors"
    assert second["version"] == 3

    after = read_control(control["id"])
    assert after["design_status"] == "DESIGN_DRAFT"
    assert after["operating_status"] == "NOT_TESTED"
    assert after["active_mapping_count"] == 0
    assert after["evidence_scheduled_count"] == 0


def test_readiness_score_is_zero_when_the_in_scope_criterion_set_is_empty(api):
    """PRD 3.3: "A catalog criterion is in scope when its `category` is a member of the
    engagement's `required_criteria_categories` *and* its `applies_to_report_types`
    contains the engagement's `report_type`."
    PRD 3.3: "A category with no in-scope criteria contributes a score of 0.00 while still
    counting toward the number of categories in the divisor."
    PRD 3.3: "The number of in-scope criteria satisfying this is
    `covered_criteria_count_readiness`, and `criteria_coverage_pct_readiness` is 100
    multiplied by that count, divided by `criteria_in_scope_count`, rounded half up to two
    decimal places — or exactly 0.00 when `criteria_in_scope_count` is 0."

    Design: Corner/calculations/corner_readiness_score_is_zero_when_no_criteria_are_in_scope
    """
    create_criterion("A1.1", category="AVAILABILITY", title="Capacity management")
    engagement = create_engagement(client_name="Empty Scope", categories=("PRIVACY",))

    summary = validate_success(api.get_readiness_summary(engagement["id"], CL_HEADERS))
    assert summary["criteria_in_scope_count"] == 0
    assert summary["covered_criteria_count_readiness"] == 0
    assert summary["covered_criteria_count_attestation"] == 0
    assert summary["criteria_coverage_pct_readiness"] == 0.00
    assert summary["criteria_coverage_pct_attestation"] == 0.00
    assert summary["readiness_score"] == 0.00
    assert summary["gap_debt_points"] == 0.00


def test_readiness_summary_mirrors_the_engagement_row_and_adds_the_decomposition(api):
    """PRD 3.5: "That same summary read is the engagement's single diagnostic surface. It
    reports `criteria_in_scope_count`, `covered_criteria_count_readiness`,
    `covered_criteria_count_attestation`, `criteria_coverage_pct_readiness`,
    `criteria_coverage_pct_attestation`, `readiness_score`, `base_debt_points`,
    `surcharge_points`, `gap_debt_points`, `gap_posture`, `open_exception_count`, and
    `open_gap_count` — the last being the number of the engagement's gaps whose `status`
    is `OPEN`, `PLANNED` or `REOPENED`."
    PRD 3.5: "`open_exception_count` itself is the number of audit exceptions whose
    control belongs to this engagement and whose `disposition` is anything other than
    `VOIDED`."

    Design: Corner/endpoints/corner_readiness_summary_computed_read_matches_engagement_row
    """
    criterion = create_criterion("CC1.1")
    engagement = create_engagement(client_name="Mirror")
    control = create_control(engagement["id"], control_ref="K-01", title="Access provisioning")
    map_control(control["id"], criterion["id"], mapping_type="PRIMARY")
    create_manual_gap(engagement["id"], severity="MODERATE", description="Policy not ratified")

    summary = validate_success(api.get_readiness_summary(engagement["id"], AUD_HEADERS))
    assert summary["criteria_in_scope_count"] == 1
    assert summary["covered_criteria_count_readiness"] == 1
    assert summary["covered_criteria_count_attestation"] == 0
    assert summary["criteria_coverage_pct_readiness"] == 100.00
    assert summary["criteria_coverage_pct_attestation"] == 0.00
    assert summary["readiness_score"] == 100.00
    assert summary["base_debt_points"] == 3
    assert summary["surcharge_points"] == 0.00
    assert summary["gap_debt_points"] == 3.00
    assert summary["gap_posture"] == "OPEN"
    assert summary["open_exception_count"] == 0
    assert summary["open_gap_count"] == 1

    row = read_engagement(engagement["id"])
    for field in (
        "criteria_in_scope_count",
        "covered_criteria_count_readiness",
        "covered_criteria_count_attestation",
        "criteria_coverage_pct_readiness",
        "criteria_coverage_pct_attestation",
        "readiness_score",
        "base_debt_points",
        "gap_debt_points",
        "gap_posture",
        "open_exception_count",
    ):
        assert summary[field] == row[field], (
            f"readiness-summary.{field} must equal the engagement row's {field}"
        )


def test_readiness_view_counts_a_secondary_mapping_on_a_merely_mapped_control(api):
    """PRD 3.3: "Under the **readiness view**, an in-scope criterion counts as covered
    when there exists at least one criteria mapping that is `ACTIVE`, that names this
    criterion, and whose control belongs to this engagement, has `in_scope` true, and has
    a `design_status` of either `DESIGN_MAPPED` or `DESIGN_APPROVED`."
    PRD 3.3: "The mapping's `mapping_type` is not consulted at all, so a `SECONDARY`
    mapping counts here; the control's `operating_status` is not consulted; and the
    criterion's `min_primary_controls` is ignored."
    PRD 3.3: "The number of in-scope criteria satisfying this is
    `covered_criteria_count_readiness`, and `criteria_coverage_pct_readiness` is 100
    multiplied by that count, divided by `criteria_in_scope_count`, rounded half up to two
    decimal places — or exactly 0.00 when `criteria_in_scope_count` is 0."

    Design: Difficulty/dual_variant_calc/coverage_readiness_view_vs_attestation_view_on_engagement
    """
    scenario = build_two_view_scenario()
    summary = validate_success(
        api.get_readiness_summary(scenario["engagement_id"], CL_HEADERS)
    )

    assert summary["criteria_in_scope_count"] == 5
    assert summary["covered_criteria_count_readiness"] == 2, (
        "CC1.1 via the PRIMARY mapping and A1.1 via the SECONDARY mapping are both covered"
    )
    assert summary["criteria_coverage_pct_readiness"] == 40.00

    engagement = read_engagement(scenario["engagement_id"])
    assert engagement["covered_criteria_count_readiness"] == 2

    k02 = read_control(scenario["controls"]["K-02"]["id"])
    assert k02["primary_mapping_count"] == 0
    assert k02["active_mapping_count"] == 1
    assert k02["design_status"] == "DESIGN_MAPPED"


def test_attestation_view_demands_a_primary_mapping_to_a_tested_effective_control(api):
    """PRD 3.3: "Under the **attestation view**, an in-scope criterion counts as covered
    only when the number of criteria mappings that are `ACTIVE`, that have `mapping_type`
    `PRIMARY`, that name this criterion, and whose control belongs to this engagement with
    `in_scope` true, `design_status` exactly `DESIGN_APPROVED` and `operating_status`
    exactly `TESTED_EFFECTIVE`, is greater than or equal to that criterion's
    `min_primary_controls`."
    PRD 3.3: "On identical data the attestation view can never exceed the readiness view
    and routinely reports strictly fewer covered criteria."

    Design: Difficulty/dual_variant_calc/coverage_readiness_view_vs_attestation_view_on_engagement
    """
    scenario = build_two_view_scenario()
    summary = validate_success(
        api.get_readiness_summary(scenario["engagement_id"], CL_HEADERS)
    )

    assert summary["covered_criteria_count_attestation"] == 0, (
        "No control has reached TESTED_EFFECTIVE, so the attestation view covers nothing"
    )
    assert summary["criteria_coverage_pct_attestation"] == 0.00
    assert_coverage_ordering(summary)

    engagement = read_engagement(scenario["engagement_id"])
    assert engagement["covered_criteria_count_attestation"] == 0
    assert read_control(scenario["controls"]["K-01"]["id"])["design_status"] == "DESIGN_APPROVED"


def test_readiness_score_rounds_each_category_before_averaging_them(api):
    """PRD 3.3: "For each category in that list, let the category total be the number of
    in-scope criteria whose `category` matches, and the category covered count be how many
    of those are covered under the readiness view."
    PRD 3.3: "**Each category's raw percentage is rounded half up to two decimal places
    first**, and only then are the rounded per-category scores summed and divided by the
    number of categories, with that mean rounded half up to two decimal places to give
    `readiness_score`."

    Design: Difficulty/combinatorial_formula/readiness_score_per_category_round_then_average_order
    """
    scenario = build_two_view_scenario()
    summary = validate_success(
        api.get_readiness_summary(scenario["engagement_id"], CL_HEADERS)
    )

    assert summary["readiness_score"] == 33.33, (
        "SECURITY 50.00, AVAILABILITY 50.00 and CONFIDENTIALITY 0.00 average to 33.33, "
        f"got {summary['readiness_score']}"
    )
    assert read_engagement(scenario["engagement_id"])["readiness_score"] == 33.33


def test_readiness_score_is_not_the_pooled_coverage_percentage(api):
    """PRD 3.3: "The alternative order — pooling covered and total counts across all
    categories and rounding once at the end — is explicitly not used and produces
    different cents."
    PRD 3.3: "The **readiness score** is a separate number and is *not* the readiness
    coverage percentage."

    Design: Difficulty/combinatorial_formula/readiness_score_per_category_round_then_average_order
    """
    scenario = build_two_view_scenario()
    summary = validate_success(
        api.get_readiness_summary(scenario["engagement_id"], CL_HEADERS)
    )

    assert summary["criteria_in_scope_count"] == 5
    assert summary["covered_criteria_count_readiness"] == 2
    assert summary["criteria_coverage_pct_readiness"] == 40.00, (
        "The pooled 2-of-5 figure is the coverage percentage"
    )
    assert summary["readiness_score"] == 33.33, (
        "The per-category mean is 33.33, not the pooled 40.00"
    )
    assert summary["readiness_score"] != summary["criteria_coverage_pct_readiness"]


def test_design_approval_before_the_boundary_is_locked_is_rejected(api):
    """PRD 3.3: "Five conditions gate it: the engagement's `boundary_locked` must be true,
    else `ERR_BOUNDARY_NOT_LOCKED`; the control's `primary_mapping_count` must be at least
    1; its `owner_user_id` must be non-null; its `in_scope` must be true; and the
    engagement's `status` must be `SCOPING`, `READINESS` or `OBSERVATION`."

    Design: Difficulty/cross_entity_state_dependency/control_design_approval_requires_locked_system_description_boundary
    """
    criterion = create_criterion("CC1.1")
    engagement = create_engagement(client_name="Alpine")
    setup_approved_locked_description(engagement["id"], lock=False)
    control = create_control(
        engagement["id"],
        control_ref="C-01",
        title="Access provisioning",
        frequency="MONTHLY",
        automation="MANUAL",
        risk_rating="MODERATE",
        population_size=20,
    )
    map_control(control["id"], criterion["id"], mapping_type="PRIMARY")
    assign_owner(control["id"], "own-1")

    response = api.transition_control(
        control["id"], {"action": "APPROVE_DESIGN"}, AUD_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_BOUNDARY_NOT_LOCKED.value, 409)

    assert read_engagement(engagement["id"])["boundary_locked"] is False
    assert read_control(control["id"])["design_status"] == "DESIGN_MAPPED", (
        "The rejected approval leaves the design track where it was"
    )


def test_design_approval_succeeds_once_the_boundary_is_locked(api):
    """PRD 3.1: "Locking sets `boundary_locked` to true on the description and on the
    engagement, and increments the engagement's `version`."
    PRD 3.3: "An `Auditor` approves a control's design, moving it `DESIGN_MAPPED →
    DESIGN_APPROVED`, by sending `action` value `APPROVE_DESIGN` together with an optional
    `reason`."

    Design: Difficulty/cross_entity_state_dependency/control_design_approval_requires_locked_system_description_boundary
    """
    criterion = create_criterion("CC1.1")
    engagement = create_engagement(client_name="Alpine")
    description = setup_approved_locked_description(engagement["id"], lock=False)
    control = create_control(
        engagement["id"],
        control_ref="C-01",
        title="Access provisioning",
        frequency="MONTHLY",
        automation="MANUAL",
        risk_rating="MODERATE",
        population_size=20,
    )
    map_control(control["id"], criterion["id"], mapping_type="PRIMARY")
    assign_owner(control["id"], "own-1")

    rejected = api.transition_control(control["id"], {"action": "APPROVE_DESIGN"}, AUD_HEADERS)
    assert rejected.status_code == 409

    locked = validate_success(api.lock_boundary(description["id"], CL_HEADERS))
    assert locked["boundary_locked"] is True
    assert read_engagement(engagement["id"])["boundary_locked"] is True

    approved = validate_success(
        api.transition_control(control["id"], {"action": "APPROVE_DESIGN"}, AUD_HEADERS)
    )
    assert approved["design_status"] == "DESIGN_APPROVED"
    assert approved["primary_mapping_count"] == 1


def test_adding_then_retiring_a_mapping_restores_the_covered_criterion_count(api):
    """PRD 3.3: "Under the **readiness view**, an in-scope criterion counts as covered
    when there exists at least one criteria mapping that is `ACTIVE`, that names this
    criterion, and whose control belongs to this engagement, has `in_scope` true, and has
    a `design_status` of either `DESIGN_MAPPED` or `DESIGN_APPROVED`."
    PRD 3.3: "Retiring a mapping is a soft delete: the row survives with `status`
    `RETIRED` and `retired_at` stamped from the logical clock, remains readable and
    listable, and stops participating in every coverage view."

    Design: Difficulty/compensating_invariant/mapping_create_then_retire_conserves_covered_criteria_count
    """
    first_criterion = create_criterion("CC1.1", title="Control environment")
    second_criterion = create_criterion("CC6.1", title="Logical access")
    engagement = create_engagement(client_name="Consolidated")
    control = create_control(
        engagement["id"],
        control_ref="K-01",
        title="Access provisioning",
        frequency="MONTHLY",
        automation="MANUAL",
        risk_rating="MODERATE",
        population_size=20,
    )
    map_control(control["id"], first_criterion["id"], mapping_type="PRIMARY")

    before = read_readiness_summary(engagement["id"])
    assert before["covered_criteria_count_readiness"] == 1
    assert before["criteria_coverage_pct_readiness"] == 50.00

    second_mapping = map_control(control["id"], second_criterion["id"], mapping_type="PRIMARY")
    middle = read_readiness_summary(engagement["id"])
    assert middle["covered_criteria_count_readiness"] == 2
    assert middle["criteria_coverage_pct_readiness"] == 100.00

    validate_success(api.retire_criteria_mapping(second_mapping["id"], CL_HEADERS))
    after = read_readiness_summary(engagement["id"])
    assert after["covered_criteria_count_readiness"] == 1, (
        "Retiring the second mapping must return the distinct covered count to exactly 1"
    )
    assert after["criteria_coverage_pct_readiness"] == 50.00


def test_mapping_retirement_restores_the_readiness_score_and_the_control_counters(api):
    """PRD 3.3: "It recomputes the control's two mapping counters, moves the control
    `DESIGN_MAPPED → DESIGN_DRAFT` when `active_mapping_count` falls to 0, and recomputes
    both coverage counts, both percentages and `readiness_score`."
    PRD 3.3: "`active_mapping_count` is the number of the control's criteria mappings
    whose `status` is `ACTIVE`, counting both mapping types; `primary_mapping_count` is
    the number of those whose `mapping_type` is additionally `PRIMARY`"

    Design: Difficulty/compensating_invariant/mapping_create_then_retire_conserves_covered_criteria_count
    """
    first_criterion = create_criterion("CC1.1", title="Control environment")
    second_criterion = create_criterion("CC6.1", title="Logical access")
    engagement = create_engagement(client_name="Consolidated")
    control = create_control(
        engagement["id"],
        control_ref="K-01",
        title="Access provisioning",
        frequency="MONTHLY",
        automation="MANUAL",
        risk_rating="MODERATE",
        population_size=20,
    )
    first_mapping = map_control(control["id"], first_criterion["id"], mapping_type="PRIMARY")

    before = read_readiness_summary(engagement["id"])
    assert before["readiness_score"] == 50.00

    second_mapping = map_control(control["id"], second_criterion["id"], mapping_type="PRIMARY")
    validate_success(api.retire_criteria_mapping(second_mapping["id"], CL_HEADERS))

    after = read_readiness_summary(engagement["id"])
    assert after["readiness_score"] == 50.00, (
        f"The readiness score must return to 50.00, got {after['readiness_score']}"
    )

    assert validate_success(api.get_criteria_mapping(second_mapping["id"], CL_HEADERS))[
        "status"
    ] == "RETIRED"
    assert validate_success(api.get_criteria_mapping(first_mapping["id"], CL_HEADERS))[
        "status"
    ] == "ACTIVE"

    control_after = read_control(control["id"])
    assert control_after["active_mapping_count"] == 1
    assert control_after["primary_mapping_count"] == 1
    assert control_after["design_status"] == "DESIGN_MAPPED"

    _, meta = validate_paginated(
        api.list_criteria_mappings(
            CL_HEADERS, params={"control_id": control["id"], "status": "ACTIVE"}
        )
    )
    assert meta["total_count"] == 1
