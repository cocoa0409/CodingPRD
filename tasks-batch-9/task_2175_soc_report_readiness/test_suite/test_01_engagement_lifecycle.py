"""Opening an engagement, its seeded derived fields, the phase ladder guards,
abandonment, listing and the logical clock."""

from test_helpers import (
    CLOCK_DEFAULT,
    MISSING_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_engagement,
    create_engagement,
    create_engagement_payload,
    create_manual_gap,
    is_iso8601_timestamp,
    is_valid_uuid,
    read_engagement,
    setup_approved_locked_description,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
    author_description,
    create_control,
    create_criterion,
    lead_engagement_action,
    assign_owner,
)

CL_HEADERS = TEST_USERS["compliance_lead_headers"]
AUD_HEADERS = TEST_USERS["auditor_headers"]
PA_HEADERS = TEST_USERS["platform_admin_headers"]


def test_new_engagement_is_seeded_in_scoping_with_zeroed_derived_fields(api):
    """PRD 3.1: "Upon registration the engagement begins in `SCOPING` with a posture
    of `OPEN` and a `version` of 1."
    PRD 3.1: "The derived fields `boundary_locked` and `approved_system_description_id`
    start false and null respectively, `readiness_assessed_at` starts null, and
    `calendar_epoch` starts at 0."
    PRD 3.1: "The server computes `observation_period_days` immediately, as the number
    of whole days in the half-open window: the difference between
    `observation_period_end` and `observation_period_start` in seconds, divided by 86400
    and truncated downward to a whole number."

    Design: Corner/entities/corner_create_engagement_returns_seeded_lifecycle_and_derived_fields
    """
    payload = create_engagement_payload(
        client_name="Northwind", max_distribution_recipients=5
    )
    response = api.create_engagement(payload, CL_HEADERS)
    data = validate_success(response, 201)

    assert_engagement(data)
    assert data["status"] == "SCOPING", f"Expected SCOPING, got {data['status']}"
    assert data["gap_posture"] == "OPEN", f"Expected OPEN, got {data['gap_posture']}"
    assert data["version"] == 1, f"A fresh engagement starts at version 1, got {data['version']}"
    assert data["observation_period_days"] == 90, (
        f"2026-09-01 to 2026-11-30 is 90 whole days, got {data['observation_period_days']}"
    )
    assert data["gap_debt_points"] == 0.00
    assert data["base_debt_points"] == 0
    assert data["open_exception_count"] == 0
    assert data["boundary_locked"] is False
    assert data["approved_system_description_id"] is None
    assert data["readiness_assessed_at"] is None
    assert data["calendar_epoch"] == 0


def test_optional_engagement_and_control_fields_take_their_declared_defaults(api):
    """PRD 3.1: "Finally, `max_distribution_recipients` is optional, defaults to 5, and
    must be at least 1; it becomes the ceiling on live report recipients described in §3.8."
    PRD 3.3: "Three optional fields have defaults: `automation` defaults to `MANUAL` and
    may be `AUTOMATED`; `risk_rating` defaults to `MODERATE` and may be `LOW` or `HIGH`;
    `population_size` defaults to 0 and must be at least 0."
    PRD 3.3: "Every counter on a fresh control — `primary_mapping_count`,
    `active_mapping_count`, `evidence_scheduled_count`, `evidence_accepted_count`,
    `evidence_missed_count`, `tested_item_count` and `open_gap_count` — starts at 0, and
    `owner_user_id` starts null."

    Design: Corner/entities/corner_engagement_and_control_defaults_apply_when_optional_fields_omitted
    """
    engagement_payload = create_engagement_payload(client_name="Defaults Co")
    engagement_payload.pop("max_distribution_recipients", None)
    engagement = validate_success(api.create_engagement(engagement_payload, CL_HEADERS), 201)
    assert engagement["max_distribution_recipients"] == 5, (
        "An omitted max_distribution_recipients must default to 5"
    )

    control = validate_success(
        api.create_control(
            {
                "engagement_id": engagement["id"],
                "control_ref": "D-01",
                "title": "Defaulted control",
                "frequency": "MONTHLY",
            },
            CL_HEADERS,
        ),
        201,
    )
    assert control["automation"] == "MANUAL"
    assert control["risk_rating"] == "MODERATE"
    assert control["population_size"] == 0
    assert control["design_status"] == "DESIGN_DRAFT"
    assert control["operating_status"] == "NOT_TESTED"
    assert control["in_scope"] is True
    assert control["owner_user_id"] is None


def test_engagement_list_reports_total_count_and_has_more(api):
    """PRD 2.3: "`limit` controls page size: it defaults to 10 when omitted, must be an
    integer of at least 1, and may not exceed 100."
    PRD 2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` is the number of rows matching the
    filters before the page window is applied and `has_more` states whether any matching
    row falls after the current window."

    Design: Corner/entities/corner_list_engagements_returns_pagination_envelope
    """
    for name in ("Alpha", "Bravo", "Charlie"):
        create_engagement(client_name=name)

    first_page, first_meta = validate_paginated(
        api.list_engagements(CL_HEADERS, params={"limit": 2, "offset": 0})
    )
    assert len(first_page) == 2, f"Expected 2 rows on the first page, got {len(first_page)}"
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert api.list_engagements(CL_HEADERS, params={"limit": 2, "offset": 0}).json()[
        "response_type"
    ] == "array"

    second_page, second_meta = validate_paginated(
        api.list_engagements(CL_HEADERS, params={"limit": 2, "offset": 2})
    )
    assert len(second_page) == 1, f"Expected 1 row on the second page, got {len(second_page)}"
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert second_meta["offset"] == 2


def test_unknown_engagement_id_reports_the_engagement_not_found_code(api):
    """PRD 2.9: "Each entity has a dedicated not-found code, and the same code is used
    whether the identifier arrived in the URL or in a request body: engagements report
    `ERR_ENGAGEMENT_NOT_FOUND`, system descriptions `ERR_SYSTEM_DESCRIPTION_NOT_FOUND`,
    boundary components `ERR_BOUNDARY_COMPONENT_NOT_FOUND`, criteria
    `ERR_TRUST_CRITERION_NOT_FOUND`, controls `ERR_CONTROL_NOT_FOUND`, mappings
    `ERR_CRITERIA_MAPPING_NOT_FOUND`, evidence requests `ERR_EVIDENCE_REQUEST_NOT_FOUND`,
    gaps `ERR_GAP_NOT_FOUND`, samples `ERR_AUDIT_SAMPLE_NOT_FOUND`, exceptions
    `ERR_AUDIT_EXCEPTION_NOT_FOUND`, subservice organizations
    `ERR_SUBSERVICE_ORG_NOT_FOUND`, complementary user entity controls
    `ERR_CUEC_NOT_FOUND`, distributions `ERR_REPORT_DISTRIBUTION_NOT_FOUND`, bridge
    letters `ERR_BRIDGE_LETTER_NOT_FOUND` and questionnaires
    `ERR_QUESTIONNAIRE_NOT_FOUND`."

    Design: Corner/entities/corner_get_engagement_with_unknown_id_returns_not_found
    """
    create_engagement(client_name="Existing")

    response = api.get_engagement(MISSING_UUID, CL_HEADERS)
    validate_error(response, ApiErrorId.ERR_ENGAGEMENT_NOT_FOUND.value, 404)
    assert response.json()["response_type"] == "error"


def test_report_type_outside_the_declared_enum_is_rejected(api):
    """PRD 3.1: "The payload names the service organization under examination as
    `client_name` (a required string of 1 to 200 characters) and declares `report_type`,
    which must be either `SOC_1_TYPE_2` or `SOC_2_TYPE_2` and which will later decide
    both which criteria are applicable and whether an addendum is added to sample sizes."
    PRD 2.7: "Every required input field present, every value of the declared type, every
    enumerated value a declared member, every count field at least 0, and every ordering
    constraint between a period start and its end, or between a coverage start and an
    as-of instant, satisfied. Otherwise `ERR_VALIDATION` (422)."

    Design: Corner/entities/corner_invalid_report_type_enum_rejected
    """
    payload = create_engagement_payload(client_name="Bad Enum", report_type="SOC_3")
    validate_error(
        api.create_engagement(payload, CL_HEADERS), ApiErrorId.ERR_VALIDATION.value, 422
    )

    _, meta = validate_paginated(api.list_engagements(CL_HEADERS))
    assert meta["total_count"] == 0, "A rejected create must store no engagement"


def test_observation_window_must_end_strictly_after_it_starts(api):
    """PRD 3.1: "The examination window is supplied as `observation_period_start` and
    `observation_period_end`, both required ISO 8601 UTC instants; the end must fall
    strictly after the start, and the window is half-open, so the start instant is inside
    the period and the end instant is not."

    Design: Corner/entities/corner_observation_period_end_before_start_rejected
    """
    payload = create_engagement_payload(
        client_name="Inverted",
        observation_period_start="2026-11-30T00:00:00.000Z",
        observation_period_end="2026-09-01T00:00:00.000Z",
    )
    validate_error(
        api.create_engagement(payload, CL_HEADERS), ApiErrorId.ERR_VALIDATION.value, 422
    )


def test_ids_timestamps_and_version_follow_the_common_field_conventions(api):
    """PRD 2.4: "Every stored resource carries a server-minted `id` — a UUID string with
    no type prefix of any kind — and a `created_at` timestamp."
    PRD 2.4: "Timestamps everywhere in this API, in request bodies and responses alike,
    are ISO 8601 UTC strings with exactly three fractional-second digits, for example
    `2026-08-01T00:00:00.000Z`."
    PRD 2.4: "Most resources additionally carry `updated_at`, refreshed on every mutation
    of that row, and `version`, an integer that starts at 1 when the row is created and
    increases by exactly one on every mutation."

    Design: Corner/entities/corner_system_minted_ids_and_timestamps_follow_common_field_conventions
    """
    engagement = create_engagement(client_name="Conventions")
    control = create_control(engagement["id"], control_ref="V-01", title="Version probe")

    assert control["version"] == 1, f"A fresh control starts at version 1, got {control['version']}"
    assert is_valid_uuid(control["id"]), "id must be a bare UUID with no type prefix"
    assert not control["id"].startswith("ctrl"), "id must carry no type prefix"
    assert is_iso8601_timestamp(control["created_at"])
    assert is_iso8601_timestamp(control["updated_at"])

    updated = assign_owner(control["id"], "own-1")
    assert updated["version"] == 2, (
        f"Assigning an owner mutates the row, so version must reach 2, got {updated['version']}"
    )
    assert updated["owner_user_id"] == "own-1"
    assert updated["updated_at"] >= updated["created_at"]


def test_start_readiness_without_an_approved_locked_description_is_rejected(api):
    """PRD 3.1: "Three conditions must hold: the engagement's
    `approved_system_description_id` is non-null, its `boundary_locked` is true, and
    `criteria_in_scope_count` is at least 1."
    PRD 2.7: "The row's own current state satisfies the requested transition's
    originating state and every precondition of that transition that does not reach into
    another entity, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/corner_start_readiness_without_approved_description_rejected
    """
    engagement = create_engagement(client_name="Premature")
    author_description(engagement["id"], version_label="v1", boundary_narrative="Draft only.")

    response = api.transition_engagement(
        engagement["id"], {"action": "START_READINESS"}, CL_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

    after = read_engagement(engagement["id"])
    assert after["status"] == "SCOPING"
    assert after["boundary_locked"] is False


def test_start_observation_without_a_readiness_assessment_is_rejected(api):
    """PRD 3.4: "Five conditions must hold: `readiness_assessed_at` is non-null, so the
    readiness assessment of §3.5 has been run at least once; the engagement's posture is
    anything but `FROZEN`; and every in-scope control of the engagement has
    `design_status` `DESIGN_APPROVED`, a non-null `owner_user_id`, and an
    `evidence_scheduled_count` of at least 1."
    PRD 2.7: "The row's own current state satisfies the requested transition's
    originating state and every precondition of that transition that does not reach into
    another entity, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/corner_start_observation_without_readiness_assessment_rejected
    """
    create_criterion("CC1.1", applies_to_report_types=("SOC_2_TYPE_2",))
    engagement = create_engagement(client_name="Gatekeeper")
    setup_approved_locked_description(engagement["id"])
    lead_engagement_action(engagement["id"], "START_READINESS")

    response = api.transition_engagement(
        engagement["id"], {"action": "START_OBSERVATION"}, CL_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

    after = read_engagement(engagement["id"])
    assert after["status"] == "READINESS"
    assert after["readiness_assessed_at"] is None
    assert after["criteria_in_scope_count"] == 1


def test_abandon_withdraws_open_gaps_and_draft_descriptions(api):
    """PRD 3.5: "It cascades: every system description of the engagement sitting in
    `DRAFT` or `IN_REVIEW` moves to `WITHDRAWN`, and every gap of the engagement sitting
    in `OPEN`, `PLANNED`, `REMEDIATED` or `REOPENED` moves to `WITHDRAWN` with its
    `debt_points` set to 0."
    PRD 3.5: "Those zeroed gaps drive a recompute of `base_debt_points`,
    `gap_debt_points` and `gap_posture`, and the engagement's `version` is incremented."

    Design: Corner/state_machines/corner_abandon_cascades_withdraw_to_gaps_and_draft_descriptions
    """
    engagement = create_engagement(client_name="Doomed")
    description = author_description(
        engagement["id"], version_label="v1", boundary_narrative="Never finished."
    )
    gap = create_manual_gap(
        engagement["id"], severity="CRITICAL", description="No security function exists"
    )

    before = validate_success(api.get_readiness_summary(engagement["id"], CL_HEADERS))
    assert before["gap_debt_points"] == 23.00, (
        f"A single CRITICAL gap gives base 20 and total 23.00, got {before['gap_debt_points']}"
    )
    assert before["gap_posture"] == "FROZEN"

    validate_success(
        api.transition_engagement(
            engagement["id"],
            {"action": "ABANDON", "reason": "Client withdrew from the examination"},
            CL_HEADERS,
        )
    )

    after = read_engagement(engagement["id"])
    assert after["status"] == "ABANDONED"
    assert after["base_debt_points"] == 0
    assert after["gap_debt_points"] == 0.00
    assert after["gap_posture"] == "OPEN"

    gap_after = validate_success(api.get_gap(gap["id"], CL_HEADERS))
    assert gap_after["status"] == "WITHDRAWN"
    assert gap_after["debt_points"] == 0

    description_after = validate_success(
        api.get_system_description(description["id"], CL_HEADERS)
    )
    assert description_after["status"] == "WITHDRAWN"


def test_abandoned_engagement_refuses_a_further_phase_transition(api):
    """PRD 3.1: "The seven-phase ladder an engagement walks is `SCOPING`, `READINESS`,
    `OBSERVATION`, `FIELDWORK`, `REPORTING` and finally `ISSUED`, with `ABANDONED`
    available as an early exit; `ISSUED` and `ABANDONED` are terminal."
    PRD 2.7: "The supplied `action`, `disposition` or `method` value is an outgoing edge
    from the row's current state, else `ERR_TRANSITION_NOT_ALLOWED` (409)."

    Design: Corner/state_machines/corner_abandoned_engagement_accepts_no_further_transitions
    """
    engagement = create_engagement(client_name="Closed Book")
    lead_engagement_action(engagement["id"], "ABANDON", reason="Scope withdrawn")

    response = api.transition_engagement(
        engagement["id"], {"action": "START_READINESS"}, CL_HEADERS
    )
    assert response.status_code == 409, (
        f"A terminal engagement must reject the transition with 409, got {response.status_code}"
    )
    validate_error_is_one_of(
        response,
        [ApiErrorId.ERR_TRANSITION_NOT_ALLOWED.value, ApiErrorId.ERR_INVALID_STATE.value],
    )
    assert read_engagement(engagement["id"])["status"] == "ABANDONED"


def test_pagination_limit_boundaries_are_inclusive_at_one_and_one_hundred(api):
    """PRD 2.3: "A `limit` outside the inclusive range 1 through 100, or a negative
    `offset`, or a non-integer value for either, is rejected with
    `ERR_INVALID_PAGINATION` (HTTP 422)."

    Design: Corner/validations/corner_pagination_limit_zero_and_over_max_rejected
    """
    create_engagement(client_name="Paginate")

    validate_error(
        api.list_engagements(CL_HEADERS, params={"limit": 0}),
        ApiErrorId.ERR_INVALID_PAGINATION.value,
        422,
    )
    validate_error(
        api.list_engagements(CL_HEADERS, params={"limit": 101}),
        ApiErrorId.ERR_INVALID_PAGINATION.value,
        422,
    )

    rows, meta = validate_paginated(
        api.list_engagements(CL_HEADERS, params={"limit": 100, "offset": 0})
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert len(rows) == 1


def test_logical_clock_reads_its_startup_default_until_it_is_set(api):
    """PRD 2.4: "Before the clock has ever been set, it reads exactly
    `2026-08-01T00:00:00.000Z`, and it never falls back to real time."
    PRD 3.1: "On success the server stamps `approved_at` with the logical clock; moves the
    engagement's previously approved description — there is at most one — from `APPROVED`
    to `SUPERSEDED`, recording that row's identifier in the new row's
    `supersedes_system_description_id`; repoints the engagement's
    `approved_system_description_id` at the newly approved row; copies that row's
    `boundary_locked` onto the engagement's own `boundary_locked`; and increments the
    engagement's `version`."
    PRD 2.4: "A `PlatformAdmin` moves it with `POST /_clock/set_current_utc`, supplying
    the target instant as `to_iso8601`; the response reports the new value as
    `current_utc`."

    Design: Corner/endpoints/corner_logical_clock_defaults_to_2026_08_01_before_any_set_call
    """
    engagement = create_engagement(client_name="Clock Probe")
    description = author_description(engagement["id"])
    validate_success(
        api.create_boundary_component(
            {
                "system_description_id": description["id"],
                "component_type": "SOFTWARE",
                "name": "Core API",
            },
            CL_HEADERS,
        ),
        201,
    )
    validate_success(
        api.transition_system_description(
            description["id"], {"action": "SUBMIT_REVIEW"}, CL_HEADERS
        )
    )

    approved = validate_success(
        api.transition_system_description(
            description["id"], {"action": "APPROVE"}, AUD_HEADERS
        )
    )
    assert approved["approved_at"] == CLOCK_DEFAULT, (
        f"Before any clock call approved_at must be {CLOCK_DEFAULT}, got {approved['approved_at']}"
    )
    assert approved["status"] == "APPROVED"

    clock = validate_success(
        api.set_clock({"to_iso8601": "2026-09-15T00:00:00.000Z"}, PA_HEADERS)
    )
    assert clock["current_utc"] == "2026-09-15T00:00:00.000Z"


def test_gap_creation_moves_the_posture_within_the_same_request_cycle(api):
    """PRD 2.9: "They are recomputed synchronously, inside the same request that changes
    their inputs, and are visible on the very next read."
    PRD 3.5: "A hand-logged gap gets `source` `MANUAL` and `status` `OPEN`, its
    `debt_points` set from its severity, an immediate recompute of the engagement's debt
    and posture, and a recompute of the control's `open_gap_count` when `control_id` is
    non-null."
    PRD 2.8: "The engagement is `FROZEN` when any of the following holds: at least one gap
    of the engagement has severity `CRITICAL` and a status of either `OPEN` or `REOPENED`;
    or `gap_debt_points` is 26.00 or more; or `open_exception_count` is 3 or more."

    Design: Corner/consistency_model/corner_derived_posture_is_visible_immediately_in_the_same_request_cycle
    """
    engagement = create_engagement(client_name="Instant")
    before = read_engagement(engagement["id"])
    assert before["gap_posture"] == "OPEN"
    assert before["gap_debt_points"] == 0.00

    gap = validate_success(
        api.create_gap(
            {
                "engagement_id": engagement["id"],
                "severity": "CRITICAL",
                "description": "No incident response capability",
            },
            CL_HEADERS,
        ),
        201,
    )
    assert gap["source"] == "MANUAL"
    assert gap["status"] == "OPEN"
    assert gap["debt_points"] == 20

    after = read_engagement(engagement["id"])
    assert after["base_debt_points"] == 20
    assert after["gap_debt_points"] == 23.00
    assert after["gap_posture"] == "FROZEN"
