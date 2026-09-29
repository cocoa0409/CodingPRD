"""The shape of the records the coalition keeps: households, cases and snapshots.

These tests read the stored row back rather than trusting the create response, and
they check the leaner immutable shape the determination snapshot uses.
"""

from test_helpers import (
    BUILDER,
    CASE_MANAGER,
    INTAKE,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_identity_fields,
    assert_immutable_record,
    assert_pagination_meta,
    assert_recovery_case,
    assert_survivor,
    assert_unmet_need_assessment,
    assert_versioned_record,
    construction_project_payload,
    create_case,
    create_project,
    create_survivor,
    document_and_verify_damage,
    is_valid_uuid,
    recovery_case_payload,
    run_assessment,
    set_clock,
    survivor_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_intake_answers_with_every_declared_household_field(api):
    """PRD §3.1: "The income term contributes 40 points for `ELI`, 30 for `VLI`, 20 for
    `LOW`, 10 for `MODERATE` and 0 for `ABOVE`. The household-size term contributes 4
    points for each household member beyond the first, so a household of one contributes
    nothing, and the term is capped at 20 points, which is reached at a household of six
    or more."

    Design: Corner/entities/corner_survivor_creation_returns_201_with_all_declared_fields
    """
    set_clock()

    created = validate_success(
        api.create_survivor(
            survivor_payload(
                household_name="Abbott Household",
                primary_contact_phone="555-0201",
                household_size=4,
                income_band="VLI",
                head_of_household_age=58,
                has_member_with_disability=True,
                is_uninsured=False,
                consent_on_file=True,
                follow_up_opt_in=True,
            ),
            INTAKE,
        ),
        201,
    )

    assert_survivor(created)
    assert created["household_name"] == "Abbott Household"
    assert created["household_size"] == 4
    assert created["income_band"] == "VLI"
    assert created["head_of_household_age"] == 58
    assert created["has_member_with_disability"] is True
    assert created["is_uninsured"] is False
    assert created["consent_on_file"] is True
    assert created["follow_up_opt_in"] is True
    # 30 for VLI + 12 for three extra members + 15 for the documented disability.
    assert created["priority_score"] == 57
    assert created["open_case_count"] == 0
    assert created["version"] == 1


def test_reading_a_household_back_answers_the_stored_row(api):
    """PRD §3.1: "A documented disability in the household adds 15 points. A head of
    household aged 65 or older adds 10 points; at 64 this term contributes nothing. Being
    uninsured adds 15 points."

    Design: Corner/entities/corner_survivor_retrieval_returns_stored_row
    """
    set_clock()
    survivor = create_survivor(
        household_name="Barlow Household",
        primary_contact_phone="555-0202",
        household_size=1,
        income_band="LOW",
        head_of_household_age=70,
        has_member_with_disability=False,
        is_uninsured=True,
        consent_on_file=True,
        follow_up_opt_in=True,
    )

    stored = validate_success(api.get_survivor(survivor["id"], CASE_MANAGER))

    assert_survivor(stored)
    assert stored["id"] == survivor["id"]
    assert stored["household_name"] == "Barlow Household"
    assert stored["household_size"] == 1
    assert stored["income_band"] == "LOW"
    assert stored["head_of_household_age"] == 70
    assert stored["is_uninsured"] is True
    # 20 for LOW + 10 for the elder head of household + 15 for being uninsured; a
    # household of one contributes nothing.
    assert stored["priority_score"] == 45
    assert stored["version"] == 1


def test_listing_a_households_cases_reports_the_full_count_and_the_window(api):
    """PRD §2.3: "Every list response reports `limit`, `offset`, `total_count` and
    `has_more` inside the `meta` object of the envelope, where `total_count` is the number
    of records matching the filters before pagination is applied and `has_more` indicates
    whether records remain beyond the current window."

    Design: Corner/entities/corner_recovery_case_listing_is_paginated_with_total_count_and_has_more
    """
    set_clock()
    survivor = create_survivor(
        household_name="Castellanos Household",
        primary_contact_phone="555-0203",
        household_size=3,
        income_band="LOW",
        head_of_household_age=44,
    )
    for disaster_code in ("DR-4801", "DR-4802", "DR-4803"):
        create_case(survivor["id"], disaster_code=disaster_code)

    first_page, first_meta = validate_paginated(
        api.list_recovery_cases(
            CASE_MANAGER, params={"survivor_id": survivor["id"], "limit": 2, "offset": 0}
        )
    )
    second_page, second_meta = validate_paginated(
        api.list_recovery_cases(
            CASE_MANAGER, params={"survivor_id": survivor["id"], "limit": 2, "offset": 2}
        )
    )

    assert len(first_page) == 2
    assert_pagination_meta(first_meta, limit=2, offset=0)
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert len(second_page) == 1
    assert_pagination_meta(second_meta, limit=2, offset=2)
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    # Each of the three cases is still open, so the household carries all three.
    household = validate_success(api.get_survivor(survivor["id"], CASE_MANAGER))
    assert household["open_case_count"] == 3


def test_reading_an_unknown_household_names_the_survivor_code(api):
    """PRD §2.11: "The response names the first identifier that failed to resolve, using
    the code for that entity kind: `ERR_SURVIVOR_NOT_FOUND`, `ERR_CASE_NOT_FOUND`,
    `ERR_DAMAGE_ITEM_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_PRESENTATION_NOT_FOUND`,
    `ERR_COMMITMENT_NOT_FOUND`, `ERR_MEMBER_ORG_NOT_FOUND`,
    `ERR_FUNDING_SOURCE_NOT_FOUND`, `ERR_DISBURSEMENT_NOT_FOUND`,
    `ERR_PROJECT_NOT_FOUND`, `ERR_VOLUNTEER_GROUP_NOT_FOUND`, `ERR_DEPLOYMENT_NOT_FOUND`,
    `ERR_LODGING_SITE_NOT_FOUND` or `ERR_HOUSING_ASSIGNMENT_NOT_FOUND`, each with HTTP
    404."

    Design: Corner/entities/corner_survivor_not_found_returns_404
    """
    set_clock()

    response = api.get_survivor(NON_EXISTENT_UUID, CASE_MANAGER)

    validate_error(response, ApiErrorId.ERR_SURVIVOR_NOT_FOUND.value, 404)
    body = response.json()
    assert body["response_type"] == "error"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]
    assert body["meta"]["api_request_id"].startswith("req_")


def test_intake_without_a_household_name_is_rejected(api):
    """PRD §2.11: "Request shape — well-formed JSON, required fields present, enum values
    legal, constrained integers within their bounds, and `limit`/`offset` within the
    pagination range (`ERR_INVALID_REQUEST`, 400). Applies to every endpoint."

    Design: Corner/entities/corner_survivor_missing_required_field_returns_invalid_request
    """
    set_clock()
    payload = survivor_payload(
        primary_contact_phone="555-0204",
        household_size=2,
        income_band="LOW",
        head_of_household_age=40,
    )
    del payload["household_name"]

    response = api.create_survivor(payload, INTAKE)

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    assert response.json()["response_type"] == "error"


def test_omitted_household_flags_take_their_declared_defaults(api):
    """PRD §3.1: "Four consent and circumstance flags round out the record:
    `has_member_with_disability`, true when at least one member has a documented
    disability, defaulting to false; `is_uninsured`, true when the household carried no
    property insurance at the time of the disaster, defaulting to false;
    `consent_on_file`, the signed release permitting the LTRG to share the case at the
    unmet needs table, defaulting to false; and `follow_up_opt_in`, the survivor's consent
    to long-term follow-up contact after closure, defaulting to true."

    Design: Corner/entities/corner_survivor_optional_flags_take_declared_defaults
    """
    set_clock()
    payload = {
        "household_name": "Duarte Household",
        "primary_contact_phone": "555-0205",
        "household_size": 2,
        "income_band": "MODERATE",
        "head_of_household_age": 41,
    }

    created = validate_success(api.create_survivor(payload, INTAKE), 201)

    assert_survivor(created)
    assert created["has_member_with_disability"] is False
    assert created["is_uninsured"] is False
    assert created["consent_on_file"] is False
    assert created["follow_up_opt_in"] is True
    # 10 for MODERATE + 4 for the one extra household member.
    assert created["priority_score"] == 14


def test_the_vulnerability_score_never_passes_one_hundred(api):
    """PRD §3.1: "The five terms are added and the total is then capped at 100, so
    `priority_score` never exceeds 100."

    Design: Corner/entities/corner_survivor_priority_score_is_computed_and_client_value_ignored
    """
    set_clock()

    created = validate_success(
        api.create_survivor(
            survivor_payload(
                household_name="Espinoza Household",
                primary_contact_phone="555-0206",
                household_size=8,
                income_band="ELI",
                head_of_household_age=70,
                has_member_with_disability=True,
                is_uninsured=True,
                consent_on_file=True,
                follow_up_opt_in=True,
            ),
            INTAKE,
        ),
        201,
    )

    # 40 for ELI + 20 for the capped household term + 15 + 10 + 15 sums to 100 exactly
    # only because the household term stops at its own cap first.
    assert_survivor(created)
    assert created["priority_score"] == 100
    assert created["open_case_count"] == 0


def test_a_new_case_is_minted_with_the_system_managed_properties(api):
    """PRD §2.4: "`version` — an integer that starts at 1 on creation and increases by
    exactly 1 on every mutation of that record."

    Design: Corner/entities/corner_case_system_fields_are_server_minted_and_version_starts_at_one
    """
    set_clock()
    survivor = create_survivor(
        household_name="Fontaine Household",
        primary_contact_phone="555-0207",
        household_size=2,
        income_band="LOW",
        head_of_household_age=50,
    )

    created = validate_success(
        api.create_recovery_case(
            recovery_case_payload(survivor["id"], disaster_code="DR-4801"), INTAKE
        ),
        201,
    )

    assert_recovery_case(created)
    assert_versioned_record(created)
    assert created["version"] == 1
    assert is_valid_uuid(created["id"])
    assert created["case_status"] == "INTAKE"
    assert created["funding_status"] == "UNFUNDED"
    assert created["total_committed_cents"] == 0
    assert created["total_net_disbursed_cents"] == 0


def test_an_income_band_outside_the_declared_five_is_rejected(api):
    """PRD §2.11: "Request shape — well-formed JSON, required fields present, enum values
    legal, constrained integers within their bounds, and `limit`/`offset` within the
    pagination range (`ERR_INVALID_REQUEST`, 400). Applies to every endpoint."

    Design: Corner/entities/corner_invalid_income_band_enum_returns_invalid_request
    """
    set_clock()

    # MIDDLE is not one of the five HUD-style bands the household record accepts.
    response = api.create_survivor(
        survivor_payload(
            household_name="Gagnon Household",
            primary_contact_phone="555-0208",
            household_size=2,
            income_band="MIDDLE",
            head_of_household_age=40,
        ),
        INTAKE,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    assert response.json()["response_type"] == "error"


def test_a_second_determination_appends_a_snapshot_rather_than_editing_one(api):
    """PRD §2.4: "Two resource kinds are deliberately leaner because they are immutable
    once written: an unmet-need determination snapshot and a follow-up contact record.
    Both carry only `id` and `created_at`. Neither carries `updated_at` and neither
    carries `version`; those two fields are absent from their responses entirely."

    Design: Corner/entities/corner_assessment_is_immutable_with_no_version_field
    """
    set_clock()
    survivor = create_survivor(
        household_name="Hollis Household",
        primary_contact_phone="555-0209",
        household_size=2,
        income_band="LOW",
        head_of_household_age=48,
    )
    case = create_case(survivor["id"])
    document_and_verify_damage(case["id"], "STRUCTURE", 900_000, description="Siding")
    first = run_assessment(case["id"], "PURPOSE_MATCHED")

    second = validate_success(
        api.create_assessment(case["id"], {"variant": "PURPOSE_MATCHED"}, CASE_MANAGER), 201
    )

    assert second["id"] != first["id"]
    for snapshot in (first, second):
        assert_immutable_record(snapshot)
        assert_unmet_need_assessment(snapshot)
        assert "version" not in snapshot
        assert "updated_at" not in snapshot
        assert snapshot["unmet_need_total_cents"] == 900_000
    listed, meta = validate_paginated(api.list_assessments(case["id"], CASE_MANAGER))
    assert meta["total_count"] == 2
    assert {row["id"] for row in listed} == {first["id"], second["id"]}


def test_opening_a_case_for_an_unknown_household_is_refused(api):
    """PRD §2.11: "Foreign keys carried in a request *body* are resolved next, and they
    too are resolved in a fixed declaration order: `survivor_id`, then `case_id`, then
    `session_id`, then `assessment_id`, then `presentation_id`, then `member_org_id`, then
    `project_id`, then `commitment_id`, then `group_id`, then `lodging_site_id`, then
    `predecessor_project_id`. An unresolvable body reference answers with the same
    per-entity 404 code — `ERR_ASSESSMENT_NOT_FOUND` for an `assessment_id`,
    `ERR_MEMBER_ORG_NOT_FOUND` for any member-organization reference including a member
    named inside `attending_member_org_ids`, and so on."

    Design: Corner/entities/corner_recovery_case_requires_existing_survivor_parent
    """
    set_clock()

    response = api.create_recovery_case(
        recovery_case_payload(NON_EXISTENT_UUID, disaster_code="DR-4801"), INTAKE
    )

    validate_error(response, ApiErrorId.ERR_SURVIVOR_NOT_FOUND.value, 404)
    _, meta = validate_paginated(
        api.list_recovery_cases(CASE_MANAGER, params={"disaster_code": "DR-4801"})
    )
    assert meta["total_count"] == 0


def test_chaining_a_phase_behind_another_households_phase_is_refused(api):
    """PRD §3.7: "An optional `predecessor_project_id` chains this phase behind an earlier
    one; it is null for a first phase, and when supplied it must name a project belonging
    to the same case, or the creation is refused with `ERR_PREDECESSOR_CASE_MISMATCH`."

    Design: Corner/entities/corner_self_referential_predecessor_must_belong_to_the_same_case
    """
    set_clock()
    survivor = create_survivor(
        household_name="Ivers Household",
        primary_contact_phone="555-0210",
        household_size=3,
        income_band="LOW",
        head_of_household_age=47,
    )
    first_case = create_case(survivor["id"], disaster_code="DR-4801")
    second_case = create_case(survivor["id"], disaster_code="DR-4802")
    predecessor = create_project(
        first_case["id"],
        scope_code="STRUCTURE_REBUILD",
        required_trade_hours={"GENERAL_LABOR": 80},
        estimated_material_cents=100_000,
    )

    cross_case = api.create_construction_project(
        construction_project_payload(
            second_case["id"],
            scope_code="INTERIOR_REPAIR",
            required_trade_hours={"GENERAL_LABOR": 120},
            estimated_material_cents=200_000,
            predecessor_project_id=predecessor["id"],
        ),
        BUILDER,
    )

    validate_error(cross_case, ApiErrorId.ERR_PREDECESSOR_CASE_MISMATCH.value, 422)
    same_case = validate_success(
        api.create_construction_project(
            construction_project_payload(
                first_case["id"],
                scope_code="INTERIOR_REPAIR",
                required_trade_hours={"GENERAL_LABOR": 120},
                estimated_material_cents=200_000,
                predecessor_project_id=predecessor["id"],
            ),
            BUILDER,
        ),
        201,
    )
    assert same_case["predecessor_project_id"] == predecessor["id"]
    assert same_case["status"] == "SCOPED"
    assert_identity_fields(same_case)
    chained, meta = validate_paginated(
        api.list_construction_projects(
            BUILDER, params={"predecessor_project_id": predecessor["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in chained] == [same_case["id"]]
