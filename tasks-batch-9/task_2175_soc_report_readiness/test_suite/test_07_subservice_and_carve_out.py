"""Subservice organizations, the buffered occupation rule on their inclusive windows,
the four-level carve-out cascade, and the frozen posture gate it can trip."""

from test_helpers import (
    MISSING_UUID,
    TEST_USERS,
    ApiErrorId,
    create_control,
    create_criterion,
    create_engagement,
    create_manual_gap,
    create_subservice_org,
    make_subservice_contact_headers,
    map_control,
    read_control,
    read_engagement,
    read_readiness_summary,
    set_subservice_method,
    validate_error,
    validate_paginated,
    validate_success,
)

CL_HEADERS = TEST_USERS["compliance_lead_headers"]


def test_subservice_contact_of_a_carve_out_organization_is_denied(api):
    """PRD 2.1: "A `SubserviceContact` whose `X-User-ID` does not name a stored
    `SubserviceOrganization`, or names one whose presentation method is not the inclusive
    one, is rejected with `ERR_SUBSERVICE_NOT_INCLUSIVE` (HTTP 403) on every endpoint whose
    role list includes `SubserviceContact`."
    PRD 3.2: "New registrations begin under the **carve-out** presentation method: `method`
    is `CARVE_OUT`, `csoc_articulated` is false, `inclusive_control_count` is 0 and
    `carved_out_at` is null."

    Design: Corner/errors/corner_subservice_contact_bound_to_carve_out_org_is_denied
    """
    engagement = create_engagement(client_name="Contact Check")
    organization = create_subservice_org(engagement["id"], name="HostCo")

    validate_error(
        api.get_engagement(
            engagement["id"], make_subservice_contact_headers(organization["id"])
        ),
        ApiErrorId.ERR_SUBSERVICE_NOT_INCLUSIVE.value,
        403,
    )
    validate_error(
        api.get_engagement(engagement["id"], make_subservice_contact_headers(MISSING_UUID)),
        ApiErrorId.ERR_SUBSERVICE_NOT_INCLUSIVE.value,
        403,
    )

    assert validate_success(
        api.get_subservice_organization(organization["id"], CL_HEADERS)
    )["method"] == "CARVE_OUT"


def build_inclusive_carve_out_scenario():
    """An INCLUSIVE subservice organization whose single control carries ACTIVE PRIMARY
    mappings to both in-scope criteria, so both are covered under the readiness view."""
    first = create_criterion("CC1.1", title="Control environment")
    second = create_criterion("CC6.1", title="Logical access")
    engagement = create_engagement(client_name="Tailspin")
    organization = create_subservice_org(
        engagement["id"],
        name="DataCo",
        services_provided="Managed hosting and backup",
    )
    set_subservice_method(organization["id"], "INCLUSIVE")
    control = create_control(
        engagement["id"],
        control_ref="T-01",
        title="DataCo backup verification",
        frequency="MONTHLY",
        automation="MANUAL",
        risk_rating="MODERATE",
        population_size=30,
        subservice_organization_id=organization["id"],
    )
    map_control(control["id"], first["id"], mapping_type="PRIMARY")
    map_control(control["id"], second["id"], mapping_type="PRIMARY")
    return {
        "engagement_id": engagement["id"],
        "organization": organization,
        "control": control,
        "criteria": {"CC1.1": first, "CC6.1": second},
    }


def test_switching_to_carve_out_drops_the_organizations_controls_out_of_scope(api):
    """PRD 3.2: "Moving `INCLUSIVE → CARVE_OUT` runs the opposite cascade, four levels
    deep, and requires `csoc_narrative` to be non-null — the complementary subservice
    organization controls narrative that the report must carry when a subservice
    organization is carved out."
    PRD 3.2: "The organization's `method` becomes `CARVE_OUT`, the supplied narrative is
    stamped onto `csoc_narrative`, `csoc_articulated` is set to true, and `carved_out_at`
    records the logical clock."
    PRD 3.2: "That method change moves every control whose `subservice_organization_id`
    names this organization to `DESIGN_CARVED_OUT` with `in_scope` set to false."

    Design: Difficulty/transitive_cascade/carve_out_switch_cascades_control_scope_to_coverage_loss_to_posture
    """
    scenario = build_inclusive_carve_out_scenario()

    before = read_readiness_summary(scenario["engagement_id"])
    assert before["criteria_coverage_pct_readiness"] == 100.00
    assert before["gap_posture"] == "OPEN"

    switched = validate_success(
        api.set_subservice_method(
            scenario["organization"]["id"],
            {
                "method": "CARVE_OUT",
                "csoc_narrative": "DataCo maintains backup encryption and restore testing controls.",
            },
            CL_HEADERS,
        )
    )
    assert switched["method"] == "CARVE_OUT"
    assert switched["csoc_articulated"] is True
    assert switched["inclusive_control_count"] == 0

    control_after = read_control(scenario["control"]["id"])
    assert control_after["design_status"] == "DESIGN_CARVED_OUT"
    assert control_after["in_scope"] is False

    engagement = read_engagement(scenario["engagement_id"])
    assert engagement["covered_criteria_count_readiness"] == 0
    assert engagement["criteria_coverage_pct_readiness"] == 0.00
    assert engagement["readiness_score"] == 0.00


def test_carve_out_synthesises_a_coverage_loss_gap_per_uncovered_criterion(api):
    """PRD 3.2: "The coverage recompute in turn synthesises one gap with `source`
    `COVERAGE_LOSS`, severity `HIGH`, a null `control_id` and a populated
    `trust_criterion_id`, for **every** in-scope criterion that was covered under the
    readiness view immediately before the call and is not covered immediately after it,
    created in ascending `criterion_code` order."
    PRD 3.2: "And those gap creations in turn drive the recompute of `base_debt_points`,
    `gap_debt_points` and `gap_posture`. A carve-out can therefore freeze an engagement in
    a single request."

    Design: Difficulty/transitive_cascade/carve_out_switch_cascades_control_scope_to_coverage_loss_to_posture
    """
    scenario = build_inclusive_carve_out_scenario()
    set_subservice_method(
        scenario["organization"]["id"],
        "CARVE_OUT",
        csoc_narrative="DataCo maintains backup encryption and restore testing controls.",
    )

    gaps, meta = validate_paginated(
        api.list_gaps(
            CL_HEADERS,
            params={"engagement_id": scenario["engagement_id"], "source": "COVERAGE_LOSS"},
        )
    )
    assert meta["total_count"] == 2, f"One gap per lost criterion, got {meta['total_count']}"
    assert gaps[0]["trust_criterion_id"] == scenario["criteria"]["CC1.1"]["id"]
    assert gaps[0]["severity"] == "HIGH"
    assert gaps[0]["control_id"] is None
    assert gaps[1]["trust_criterion_id"] == scenario["criteria"]["CC6.1"]["id"]
    assert gaps[1]["severity"] == "HIGH"
    assert gaps[1]["control_id"] is None

    engagement = read_engagement(scenario["engagement_id"])
    assert engagement["base_debt_points"] == 16
    assert engagement["gap_debt_points"] == 18.40
    assert engagement["gap_posture"] == "RESTRICTED"


def build_three_subservice_windows():
    """Three carve-out organizations: SS-A covers September, SS-B starts the day after
    SS-A ends, and SS-C starts two days after SS-A ends."""
    engagement = create_engagement(client_name="Fabrikam")
    a = create_subservice_org(
        engagement["id"],
        name="SS-A",
        services_provided="Primary hosting",
        coverage_start="2026-09-01T00:00:00.000Z",
        coverage_end="2026-09-30T00:00:00.000Z",
    )
    b = create_subservice_org(
        engagement["id"],
        name="SS-B",
        services_provided="Failover hosting",
        coverage_start="2026-10-01T00:00:00.000Z",
        coverage_end="2026-10-31T00:00:00.000Z",
    )
    c = create_subservice_org(
        engagement["id"],
        name="SS-C",
        services_provided="Archive hosting",
        coverage_start="2026-10-02T00:00:00.000Z",
        coverage_end="2026-10-31T00:00:00.000Z",
    )
    return engagement, a, b, c


def test_an_adjacent_inclusive_window_leaves_no_clear_space_and_is_rejected(api):
    """PRD 3.2: "For each such neighbour, take whichever of the two closed windows ends
    first and call it the earlier; the clear space between them is the difference between
    the later window's `coverage_start` and the earlier window's `coverage_end` in seconds,
    divided by 86400, truncated downward to a whole number, and then reduced by one."
    PRD 3.2: "That clear space must be at least 1 whole day. Overlapping windows produce a
    negative clear space and adjacent windows — where the later start falls exactly one day
    after the earlier end — produce zero, so both are rejected with
    `ERR_SUBSERVICE_WINDOW_BUFFER`."

    Design: Difficulty/resource_temporal_overlap/inclusive_subservice_windows_require_a_whole_day_buffer
    """
    _, a, b, _ = build_three_subservice_windows()

    first = validate_success(
        api.set_subservice_method(a["id"], {"method": "INCLUSIVE"}, CL_HEADERS)
    )
    assert first["method"] == "INCLUSIVE"

    response = api.set_subservice_method(b["id"], {"method": "INCLUSIVE"}, CL_HEADERS)
    validate_error(response, ApiErrorId.ERR_SUBSERVICE_WINDOW_BUFFER.value, 409)

    stored = validate_success(api.get_subservice_organization(b["id"], CL_HEADERS))
    assert stored["method"] == "CARVE_OUT"
    assert stored["csoc_articulated"] is False


def test_a_whole_day_of_clear_space_lets_the_second_window_go_inclusive(api):
    """PRD 3.2: "That clear space must be at least 1 whole day. Overlapping windows produce
    a negative clear space and adjacent windows — where the later start falls exactly one
    day after the earlier end — produce zero, so both are rejected with
    `ERR_SUBSERVICE_WINDOW_BUFFER`."
    PRD 3.2: "On success `method` becomes `INCLUSIVE` while `carved_out_at` is left
    untouched, every control of that organization sitting in `DESIGN_CARVED_OUT` returns to
    `DESIGN_DRAFT` with `in_scope` set back to true, `inclusive_control_count` is
    recomputed, and both of the engagement's coverage percentages are recomputed."

    Design: Difficulty/resource_temporal_overlap/inclusive_subservice_windows_require_a_whole_day_buffer
    """
    engagement, a, b, c = build_three_subservice_windows()
    set_subservice_method(a["id"], "INCLUSIVE")

    rejected = api.set_subservice_method(b["id"], {"method": "INCLUSIVE"}, CL_HEADERS)
    assert rejected.status_code == 409

    accepted = validate_success(
        api.set_subservice_method(c["id"], {"method": "INCLUSIVE"}, CL_HEADERS)
    )
    assert accepted["method"] == "INCLUSIVE", (
        "A start two days after the neighbour's end leaves one whole clear day"
    )

    _, meta = validate_paginated(
        api.list_subservice_organizations(
            CL_HEADERS, params={"engagement_id": engagement["id"], "method": "INCLUSIVE"}
        )
    )
    assert meta["total_count"] == 2


def build_frozen_out_of_scope_scenario():
    """A frozen engagement (one OPEN CRITICAL gap) whose control belongs to a carve-out
    subservice organization and is therefore out of scope."""
    criterion = create_criterion("CC1.1")
    engagement = create_engagement(client_name="Litware")
    organization = create_subservice_org(
        engagement["id"], name="HostCo", services_provided="Colocation"
    )
    control = create_control(
        engagement["id"],
        control_ref="P-01",
        title="Colocation access log review",
        frequency="MONTHLY",
        automation="MANUAL",
        risk_rating="MODERATE",
        population_size=10,
        subservice_organization_id=organization["id"],
    )
    create_manual_gap(
        engagement["id"], severity="CRITICAL", description="No incident response capability"
    )
    return {
        "engagement_id": engagement["id"],
        "criterion": criterion,
        "control": control,
    }


def test_a_frozen_engagement_reports_the_freeze_not_the_out_of_scope_control(api):
    """PRD 2.7: "**Engagement not frozen**, else `ERR_ENGAGEMENT_FROZEN` (409). A frozen
    engagement rejects every gated child mutation *regardless of any later business rule the
    same request would also violate*."
    PRD 2.8: "A frozen engagement rejects, with `ERR_ENGAGEMENT_FROZEN`, six operations:
    creating a criteria mapping, retiring a criteria mapping, submitting evidence, reviewing
    evidence, delivering a report distribution, and issuing a bridge letter."

    Design: Difficulty/priority_pair_validation_conflict/frozen_posture_state_beats_control_out_of_scope_referential
    """
    scenario = build_frozen_out_of_scope_scenario()

    response = api.create_criteria_mapping(
        {
            "control_id": scenario["control"]["id"],
            "trust_criterion_id": scenario["criterion"]["id"],
            "mapping_type": "PRIMARY",
        },
        CL_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_ENGAGEMENT_FROZEN.value, 409)

    engagement = read_engagement(scenario["engagement_id"])
    assert engagement["gap_posture"] == "FROZEN"
    assert engagement["base_debt_points"] == 20
    assert engagement["gap_debt_points"] == 23.00


def test_the_frozen_rejection_stores_no_mapping_on_the_out_of_scope_control(api):
    """PRD 3.3: "The referenced control must have `in_scope` true and a `design_status`
    other than `DESIGN_CARVED_OUT`, else `ERR_CONTROL_OUT_OF_SCOPE`; the referenced
    criterion must be in scope for the engagement, else `ERR_CRITERION_OUT_OF_SCOPE`; and
    the pair of `control_id` and `trust_criterion_id` must not already exist among that
    control's active mappings, else `ERR_DUPLICATE_RESOURCE`."
    PRD 3.3: "The new control's `in_scope` is true when `subservice_organization_id` is
    null or when the named organization is presented inclusively, and false otherwise, and
    registering a control against an organization recomputes that organization's
    `inclusive_control_count`."

    Design: Difficulty/priority_pair_validation_conflict/frozen_posture_state_beats_control_out_of_scope_referential
    """
    scenario = build_frozen_out_of_scope_scenario()

    rejected = api.create_criteria_mapping(
        {
            "control_id": scenario["control"]["id"],
            "trust_criterion_id": scenario["criterion"]["id"],
            "mapping_type": "PRIMARY",
        },
        CL_HEADERS,
    )
    assert rejected.status_code == 409

    control_after = read_control(scenario["control"]["id"])
    assert control_after["in_scope"] is False, (
        "The control belongs to a carve-out organization and is therefore out of scope"
    )
    assert control_after["active_mapping_count"] == 0

    _, meta = validate_paginated(
        api.list_criteria_mappings(
            CL_HEADERS, params={"control_id": scenario["control"]["id"]}
        )
    )
    assert meta["total_count"] == 0
