"""Chapter, standard, unit and observation records: declared fields, server-owned
defaults, ignored client input, path/body resolution order and collection reads."""

from test_helpers import (
    SURVEYOR_USER_ID,
    UNKNOWN_UUIDS,
    ApiErrorId,
    assert_append_only_fields,
    assert_chapter,
    assert_hospital_unit,
    assert_standard,
    assert_three_fractional_digits,
    assert_tracer_observation,
    assign_owner,
    create_chapter,
    create_standard,
    create_survey_window,
    create_unit,
    evidence_action,
    file_evidence,
    make_standard_owner_headers,
    open_rounding_session,
    raise_deficiency,
    schedule_tracer,
    set_clock,
    tracer_action,
    validate_error,
    validate_paginated,
    validate_success,
    window_action,
)


# ---------------------------------------------------------------------------
# Private setup chains — every test rebuilds its own world from scratch.
# ---------------------------------------------------------------------------

def _setup_unit_with_three_life_safety_tickets():
    """Chapter LS with one standard, unit ED-2, and one OPEN LIFE_SAFETY session
    carrying three tickets of severity LOW, LOW and MODERATE."""
    chapter = create_chapter("LS", "Life Safety", 25, 1)
    standard = create_standard(
        chapter["id"], "LS.02.01.01", "Sprinkler coverage", "INDIRECT_IMPACT"
    )
    unit = create_unit("ED-2", "ED", 20)
    set_clock("2026-08-10T00:00:00Z")
    session = open_rounding_session(
        unit["id"], "LIFE_SAFETY", "2026-08-10T08:00:00Z", "2026-08-10T12:00:00Z"
    )
    tickets = [
        raise_deficiency(
            session["id"], standard["id"], "LOW", "Storage within 18 inches of sprinkler"
        ),
        raise_deficiency(session["id"], standard["id"], "LOW", "Corridor cart unattended"),
        raise_deficiency(
            session["id"], standard["id"], "MODERATE", "Fire drill record incomplete"
        ),
    ]
    return {"chapter": chapter, "standard": standard, "unit": unit,
            "session": session, "tickets": tickets}


def _setup_in_progress_tracer():
    """Chapter EC mapped through one owned standard, unit MED-1, and one tracer
    started inside its window at the logical clock 2026-08-05T09:00:00Z."""
    chapter = create_chapter("EC", "Environment of Care", 100, 1)
    standard = create_standard(chapter["id"], "EC.02.06.01", "Safe environment", "DIRECT_IMPACT")
    assign_owner(standard["id"], "owner-1", "PRIMARY")
    unit = create_unit("MED-1", "MED_SURG", 24)
    tracer = schedule_tracer(
        unit["id"],
        chapter["id"],
        "2026-08-05T08:00:00Z",
        "2026-08-05T10:00:00Z",
        expected_unit_version=unit["version"],
    )
    set_clock("2026-08-05T09:00:00Z")
    tracer = tracer_action(tracer["id"], "START")
    return {"chapter": chapter, "standard": standard, "unit": unit, "tracer": tracer}


def _setup_active_survey_with_standard():
    """Chapter EM with one standard and survey CYCLE-2026 driven to ACTIVE_SURVEY
    at the logical clock 2026-09-20T00:00:00Z, with no hospital unit registered."""
    chapter = create_chapter("EM", "Emergency Management", 20, 1)
    standard = create_standard(
        chapter["id"], "EM.02.01.01", "Emergency operations plan", "INDIRECT_IMPACT"
    )
    window = create_survey_window("CYCLE-2026", "2025-03-15T00:00:00Z")
    set_clock("2026-09-20T00:00:00Z")
    window_action(window["id"], "ACTIVATE_COMMAND_CENTER")
    window = window_action(window["id"], "OPEN_SURVEY")
    return {"chapter": chapter, "standard": standard, "window": window}


# ---------------------------------------------------------------------------
# Chapter and standard records
# ---------------------------------------------------------------------------

def test_chapter_registration_returns_declared_fields_and_zeroed_counters(
    api, director_headers
):
    """PRD §3.1: "An `AccreditationDirector` registers a chapter with a `code` — two to four uppercase letters, unique across all chapters, drawn from the accreditation body's chapter set such as EC, LS, IC, MM, NPSG, EM and PC — a human-readable `name`, and a `weight_pct` expressing how much of a unit's readiness score that chapter is responsible for."

    PRD §3.1: "A freshly registered chapter is an empty shell with every derived counter at zero — `standard_count`, `mapped_standard_count`, `evidence_complete_standard_count`, `deficient_standard_count` and `ppr_escalation_count` — and a `readiness_flag` of `ON_TRACK`."

    PRD §2.5: "Most resources additionally carry `updated_at`, an ISO 8601 UTC instant in the same format that is refreshed on every mutation, and `version`, an integer that starts at 1 when the resource is created and increases by one on every mutation of that resource."

    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."

    PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."

    Design: Corner/entities/chapter_creation_returns_declared_fields_and_defaults
    """
    response = api.create_chapter(
        {"code": "EC", "name": "Environment of Care", "weight_pct": 100,
         "evidence_min_count": 1},
        director_headers,
    )
    chapter = validate_success(response, 201)
    assert_chapter(chapter)

    assert chapter["code"] == "EC"
    assert chapter["name"] == "Environment of Care"
    assert float(chapter["weight_pct"]) == 100
    assert chapter["evidence_min_count"] == 1

    assert chapter["standard_count"] == 0
    assert chapter["mapped_standard_count"] == 0
    assert chapter["evidence_complete_standard_count"] == 0
    assert chapter["deficient_standard_count"] == 0
    assert chapter["ppr_escalation_count"] == 0
    assert chapter["readiness_flag"] == "ON_TRACK"
    assert chapter["version"] == 1
    assert_three_fractional_digits(chapter["created_at"])

    envelope = response.json()
    assert envelope["response_type"] == "object"
    assert envelope["meta"]["api_request_id"].startswith("req_")
    assert_three_fractional_digits(envelope["meta"]["api_request_timestamp"])


def test_standard_read_echoes_stored_code_tier_and_unmapped_state(
    api, standard_owner_headers
):
    """PRD §3.1: "Adding a standard to a chapter is likewise reserved to the `AccreditationDirector`, who supplies a `standard_code` such as EC.02.06.01, a `title` summarising the standard text, and a `risk_tier` of `DIRECT_IMPACT`, `INDIRECT_IMPACT` or `SITUATIONAL_DECISION_RULE`."

    PRD §3.1: "The new standard begins at `compliance_state` `UNMAPPED`, with `active_owner_count` and `validated_evidence_count` at zero and `last_noncompliant_observed_at` null."

    PRD §3.1: "Creating the standard increments the chapter's `standard_count` and mutates the chapter."

    PRD §2.8: "A standard's `chapter_id`, an owner assignment's and an evidence item's `standard_id`, an observation's `mock_tracer_id`, a deficiency ticket's `rounding_session_id`, a finding's `survey_window_id`, a submission's `survey_finding_id` and a self-assessment's `chapter_id` are all derived this way."

    PRD §2.1: "Every read operation in the system is available to all seven roles."

    Design: Corner/entities/standard_retrieval_returns_stored_row
    """
    chapter = create_chapter("EC", "Environment of Care", 100, 1)
    created = create_standard(
        chapter["id"], "EC.02.06.01", "Safe environment", "DIRECT_IMPACT"
    )

    standard = validate_success(api.get_standard(created["id"], standard_owner_headers))
    assert_standard(standard)

    assert standard["standard_code"] == "EC.02.06.01"
    assert standard["title"] == "Safe environment"
    assert standard["risk_tier"] == "DIRECT_IMPACT"
    assert standard["compliance_state"] == "UNMAPPED"
    assert standard["active_owner_count"] == 0
    assert standard["validated_evidence_count"] == 0
    assert standard["last_noncompliant_observed_at"] is None
    assert standard["chapter_id"] == chapter["id"]

    reread = validate_success(api.get_chapter(chapter["id"], standard_owner_headers))
    assert reread["standard_count"] == 1


def test_chapter_standards_listing_filters_by_compliance_state(
    api, evidence_validator_headers
):
    """PRD §2.3: "The standards of a chapter may be filtered by `compliance_state`; the owner assignments of a standard by `status`; a standard's evidence repository by `validation_state`; the mock tracer collection by `unit_id`, `chapter_id` and `state`; both observation collections — the one scoped to a tracer and the one scoped to a standard — by `result`; the rounding-session collection by `unit_id`, `round_type` and `state`; the deficiency-ticket collection by `rounding_session_id`, `standard_id`, `state` and `severity`; the survey-finding collection by `survey_window_id`, `standard_id`, `unit_id` and `state`; and a chapter's periodic performance review collection by `state`."

    PRD §2.3: "Unless a specific endpoint says otherwise, every collection is sorted by `created_at` in ascending order."

    PRD §3.1: "If that count moved from zero to one, the standard transitions `UNMAPPED → MAPPED` and its chapter's `mapped_standard_count` increases by one — the count only moves on that zero-to-one edge, so a second owner leaves it alone."

    Design: Corner/endpoints/chapter_standards_listing_filters_by_compliance_state
    """
    chapter = create_chapter("EC", "Environment of Care", 100, 1)
    first = create_standard(chapter["id"], "EC.02.06.01", "Safe environment", "DIRECT_IMPACT")
    second = create_standard(
        chapter["id"], "EC.02.05.01", "Utility systems", "INDIRECT_IMPACT"
    )
    assign_owner(first["id"], "owner-1", "PRIMARY")

    filtered, filtered_meta = validate_paginated(
        api.list_chapter_standards(
            chapter["id"],
            evidence_validator_headers,
            {"compliance_state": "MAPPED", "limit": 10, "offset": 0},
        )
    )
    assert filtered_meta["total_count"] == 1
    assert filtered_meta["has_more"] is False
    assert len(filtered) == 1
    assert filtered[0]["id"] == first["id"]
    assert filtered[0]["compliance_state"] == "MAPPED"

    everything, all_meta = validate_paginated(
        api.list_chapter_standards(
            chapter["id"], evidence_validator_headers, {"limit": 10, "offset": 0}
        )
    )
    assert all_meta["total_count"] == 2
    assert [row["standard_code"] for row in everything] == ["EC.02.06.01", "EC.02.05.01"]
    assert second["id"] in [row["id"] for row in everything]
    assert second["id"] not in [row["id"] for row in filtered]


def test_chapter_evidence_min_count_defaults_to_two_and_holds_standard_in_mapped(
    api, director_headers, evidence_validator_headers
):
    """PRD §3.1: "The chapter also declares `evidence_min_count`, the number of validated documents a standard in that chapter must accumulate before it counts as evidence-complete; when the field is omitted it defaults to 2, and any supplied value must be at least 1."

    PRD §3.2: "When those pass, the item moves `SUBMITTED → VALIDATED`, `reviewed_by_user_id` is set to the reviewing principal and `review_note` is captured from the payload, and the standard's `validated_evidence_count` increases by one."

    PRD §3.2: "If that increase brings the count to at least the owning chapter's `evidence_min_count`, the standard transitions `MAPPED → EVIDENCE_COMPLETE` and the chapter's `evidence_complete_standard_count` increases by one."

    Design: Corner/entities/chapter_evidence_min_count_default_two_applied
    """
    chapter = validate_success(
        api.create_chapter(
            {"code": "MM", "name": "Medication Management", "weight_pct": 30},
            director_headers,
        ),
        201,
    )
    assert chapter["evidence_min_count"] == 2

    standard = create_standard(
        chapter["id"], "MM.05.01.01", "Medication order review", "INDIRECT_IMPACT"
    )
    assign_owner(standard["id"], "owner-1", "PRIMARY")
    evidence = file_evidence(
        standard["id"], "Order review policy", "POLICY", "2026-07-01T00:00:00Z",
        owner_user_id="owner-1",
    )
    evidence_action(evidence["id"], "SUBMIT", make_standard_owner_headers("owner-1"))

    validated = validate_success(
        api.transition_evidence_item(
            evidence["id"],
            {"action": "VALIDATE", "review_note": "Policy accepted"},
            evidence_validator_headers,
        )
    )
    assert validated["validation_state"] == "VALIDATED"

    reread = validate_success(api.get_standard(standard["id"], director_headers))
    assert reread["validated_evidence_count"] == 1
    assert reread["compliance_state"] == "MAPPED"

    chapter_after = validate_success(api.get_chapter(chapter["id"], director_headers))
    assert chapter_after["evidence_complete_standard_count"] == 0
    assert chapter_after["mapped_standard_count"] == 1


def test_chapter_creation_ignores_client_supplied_computed_counters(api, director_headers):
    """PRD §3.1: "A freshly registered chapter is an empty shell with every derived counter at zero — `standard_count`, `mapped_standard_count`, `evidence_complete_standard_count`, `deficient_standard_count` and `ppr_escalation_count` — and a `readiness_flag` of `ON_TRACK`."

    PRD §3.1: "It flips from `ON_TRACK` to `AT_RISK` as soon as either the chapter accumulates two or more deficient standards or its overstatement escalations reach two."

    PRD §1: "The second is **conserved derived state**: every counter, ledger and score in the system is a pure function of the rows beneath it, and every operation that changes those rows must propagate the consequence immediately, in the same request, all the way up the graph."

    Design: Corner/entities/chapter_computed_counter_input_ignored
    """
    chapter = validate_success(
        api.create_chapter(
            {
                "code": "PC",
                "name": "Provision of Care",
                "weight_pct": 40,
                "evidence_min_count": 1,
                "mapped_standard_count": 99,
                "readiness_flag": "AT_RISK",
            },
            director_headers,
        ),
        201,
    )
    assert chapter["mapped_standard_count"] == 0
    assert chapter["readiness_flag"] == "ON_TRACK"
    assert float(chapter["weight_pct"]) == 40

    reread = validate_success(api.get_chapter(chapter["id"], director_headers))
    assert reread["mapped_standard_count"] == 0
    assert reread["readiness_flag"] == "ON_TRACK"
    assert float(reread["weight_pct"]) == 40


def test_standard_creation_under_unknown_chapter_returns_chapter_not_found(
    api, director_headers
):
    """PRD §2.8: "A request addressed at a standard nested under a chapter fails with `ERR_CHAPTER_NOT_FOUND` when the chapter does not exist, before the standard is looked up at all."

    PRD §2.11: "5. Path existence, left to right — the eleven 404 codes of §2.8, on every endpoint with a path identifier."

    Design: Corner/entities/standard_creation_under_unknown_chapter_not_found
    """
    response = api.create_standard(
        UNKNOWN_UUIDS["chapter"],
        {"standard_code": "EC.02.06.01", "title": "Safe environment",
         "risk_tier": "DIRECT_IMPACT"},
        director_headers,
    )
    validate_error(response, ApiErrorId.ERR_CHAPTER_NOT_FOUND)


def test_chapter_registration_without_weight_pct_returns_invalid_request(
    api, director_headers
):
    """PRD §2.11: "3. Request shape: every required body field is present, every enum value is a member of its declared set, every number is within range, and `self_ratings` contains no duplicated `standard_id` — `ERR_INVALID_REQUEST`, 400, on every write endpoint."

    PRD §3.1: "An `AccreditationDirector` registers a chapter with a `code` — two to four uppercase letters, unique across all chapters, drawn from the accreditation body's chapter set such as EC, LS, IC, MM, NPSG, EM and PC — a human-readable `name`, and a `weight_pct` expressing how much of a unit's readiness score that chapter is responsible for."

    Design: Corner/entities/chapter_missing_required_weight_pct_returns_invalid_request
    """
    response = api.create_chapter(
        {"code": "IC", "name": "Infection Control"}, director_headers
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

    # The rejected request created nothing, so code IC is still free to register.
    accepted = validate_success(
        api.create_chapter(
            {"code": "IC", "name": "Infection Control", "weight_pct": 50,
             "evidence_min_count": 1},
            director_headers,
        ),
        201,
    )
    assert accepted["standard_count"] == 0


# ---------------------------------------------------------------------------
# Hospital unit records
# ---------------------------------------------------------------------------

def test_unit_registration_ignores_client_supplied_system_fields(api, director_headers):
    """PRD §2.5: "Every resource in the system carries a server-minted `id`, formatted as a UUID with no type prefix, and a `created_at` timestamp rendered as an ISO 8601 UTC instant with three fractional digits (for example `2026-08-01T00:00:00.000Z`)."

    PRD §2.5: "Most resources additionally carry `updated_at`, an ISO 8601 UTC instant in the same format that is refreshed on every mutation, and `version`, an integer that starts at 1 when the resource is created and increases by one on every mutation of that resource."

    PRD §3.3: "The new unit starts with `posture` `OPEN`, `open_deficiency_penalty_points` at zero, `scheduled_tracer_count` at zero, `readiness_score` at 0.00 and `readiness_band` `NOT_ASSESSED`."

    Design: Corner/entities/unit_system_fields_input_ignored
    """
    unit = validate_success(
        api.create_unit(
            {
                "name": "ICU-1",
                "unit_type": "ICU",
                "bed_count": 12,
                "id": "22222222-2222-4222-8222-222222222222",
                "created_at": "2020-01-01T00:00:00Z",
                "version": 77,
            },
            director_headers,
        ),
        201,
    )
    assert_hospital_unit(unit)

    assert unit["id"] != "22222222-2222-4222-8222-222222222222"
    assert unit["version"] == 1
    assert_three_fractional_digits(unit["created_at"])
    assert not unit["created_at"].startswith("2020")

    assert unit["posture"] == "OPEN"
    assert float(unit["readiness_score"]) == 0.00
    assert unit["readiness_band"] == "NOT_ASSESSED"
    assert unit["scheduled_tracer_count"] == 0
    assert unit["open_deficiency_penalty_points"] == 0


def test_unit_registration_with_undeclared_unit_type_returns_invalid_request(
    api, director_headers
):
    """PRD §3.3: "An `AccreditationDirector` registers one with a `name` that must be unique across the hospital — `ICU-3`, for example — a `unit_type` of `MED_SURG`, `ICU`, `ED`, `OR`, `BEHAVIORAL_HEALTH` or `AMBULATORY`, and a `bed_count` that must be at least zero."

    PRD §2.11: "3. Request shape: every required body field is present, every enum value is a member of its declared set, every number is within range, and `self_ratings` contains no duplicated `standard_id` — `ERR_INVALID_REQUEST`, 400, on every write endpoint."

    Design: Corner/entities/unit_invalid_enum_unit_type_rejected
    """
    response = api.create_unit(
        {"name": "HELIPAD-1", "unit_type": "HELIPAD", "bed_count": 0}, director_headers
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

    # No unit was stored, so the name HELIPAD-1 is still available hospital-wide.
    accepted = validate_success(
        api.create_unit(
            {"name": "HELIPAD-1", "unit_type": "AMBULATORY", "bed_count": 0},
            director_headers,
        ),
        201,
    )
    assert accepted["unit_type"] == "AMBULATORY"


def test_readiness_read_for_unknown_unit_returns_unit_not_found(api, director_headers):
    """PRD §2.8: "The eleven not-found codes map one-to-one onto the eleven addressable resources: `ERR_CHAPTER_NOT_FOUND`, `ERR_STANDARD_NOT_FOUND`, `ERR_OWNER_ASSIGNMENT_NOT_FOUND`, `ERR_EVIDENCE_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_TRACER_NOT_FOUND`, `ERR_ROUNDING_SESSION_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_SURVEY_WINDOW_NOT_FOUND`, `ERR_FINDING_NOT_FOUND` and `ERR_PPR_NOT_FOUND`, all at HTTP 404."

    PRD §2.11: "5. Path existence, left to right — the eleven 404 codes of §2.8, on every endpoint with a path identifier."

    Design: Corner/entities/readiness_read_for_unknown_unit_returns_not_found
    """
    response = api.get_unit_readiness(UNKNOWN_UUIDS["unit"], director_headers)
    error = validate_error(response, ApiErrorId.ERR_UNIT_NOT_FOUND)

    assert response.json()["response_type"] == "error"
    assert error["message"].strip()


# ---------------------------------------------------------------------------
# Deficiency ticket collection reads
# ---------------------------------------------------------------------------

def test_deficiency_ticket_listing_paginates_with_total_count(api, safety_officer_headers):
    """PRD §2.3: "The `meta` object of every collection response carries `limit`, `offset`, `total_count` and `has_more`, where `total_count` is the size of the filtered result set before pagination is applied and `has_more` indicates whether rows remain beyond the current page."

    PRD §2.3: "`offset` is the number of rows to skip; when omitted it defaults to 0 and its minimum accepted value is 0."

    PRD §3.5: "Creating a ticket also increments the session's `deficiency_count` by one and advances the unit's `version`."

    PRD §2.9: "The **unit penalty ledger** pins `HospitalUnit.open_deficiency_penalty_points` to the sum of `penalty_points` over every deficiency ticket of that unit that has not reached `VERIFIED` — that is, every ticket in `OPEN`, `IN_PROGRESS`, `REMEDIATED` or `ESCALATED`."

    PRD §3.5: "**Fifth**, `penalty_points` is set from the severity — one point for `LOW`, three for `MODERATE`, seven for `HIGH`, fifteen for `IMMEDIATE_THREAT`."

    Design: Corner/entities/deficiency_ticket_listing_paginates_with_total_count
    """
    built = _setup_unit_with_three_life_safety_tickets()
    session_id = built["session"]["id"]

    page_one, meta_one = validate_paginated(
        api.list_deficiency_tickets(
            safety_officer_headers,
            {"rounding_session_id": session_id, "limit": 2, "offset": 0},
        )
    )
    assert len(page_one) == 2
    assert meta_one["total_count"] == 3
    assert meta_one["limit"] == 2
    assert meta_one["offset"] == 0
    assert meta_one["has_more"] is True

    page_two, meta_two = validate_paginated(
        api.list_deficiency_tickets(
            safety_officer_headers,
            {"rounding_session_id": session_id, "limit": 2, "offset": 2},
        )
    )
    assert len(page_two) == 1
    assert meta_two["total_count"] == 3
    assert meta_two["offset"] == 2
    assert meta_two["has_more"] is False

    seen = [row["id"] for row in page_one] + [row["id"] for row in page_two]
    assert sorted(seen) == sorted(ticket["id"] for ticket in built["tickets"])

    session = validate_success(api.get_rounding_session(session_id, safety_officer_headers))
    assert session["deficiency_count"] == 3

    unit = validate_success(api.get_unit(built["unit"]["id"], safety_officer_headers))
    assert unit["open_deficiency_penalty_points"] == 5


# ---------------------------------------------------------------------------
# Append-only tracer observations
# ---------------------------------------------------------------------------

def test_tracer_observation_carries_no_version_or_updated_at(
    api, tracer_surveyor_headers
):
    """PRD §2.5: "Two resources are append-only records of a moment and therefore carry **only** `id` and `created_at`: `TracerObservation` and `EscSubmission`."

    PRD §2.5: "Both `updated_at` and `version` are absent from those two resources entirely."

    PRD §3.4: "The server stamps `recorded_by_user_id` with the acting surveyor's identifier."

    PRD §3.4: "No scoring whatsoever happens at observation time; observations accumulate silently until the tracer is closed out."

    Design: Corner/entities/tracer_observation_is_immutable_without_version_field
    """
    built = _setup_in_progress_tracer()
    tracer_id = built["tracer"]["id"]

    observation = validate_success(
        api.create_tracer_observation(
            tracer_id,
            {"standard_id": built["standard"]["id"], "result": "COMPLIANT",
             "weight": 3, "note": "Two rooms sampled"},
            tracer_surveyor_headers,
        ),
        201,
    )
    assert_tracer_observation(observation)
    assert_append_only_fields(observation)

    assert observation["mock_tracer_id"] == tracer_id
    assert observation["standard_id"] == built["standard"]["id"]
    assert observation["result"] == "COMPLIANT"
    assert float(observation["weight"]) == 3
    assert observation["note"] == "Two rooms sampled"
    assert observation["recorded_by_user_id"] == SURVEYOR_USER_ID
    assert "version" not in observation
    assert "updated_at" not in observation

    rows, meta = validate_paginated(
        api.list_tracer_observations(tracer_id, tracer_surveyor_headers)
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert_append_only_fields(rows[0])

    tracer = validate_success(api.get_mock_tracer(tracer_id, tracer_surveyor_headers))
    assert tracer["state"] == "IN_PROGRESS"
    assert float(tracer["tracer_score"]) == 0.00


# ---------------------------------------------------------------------------
# Body foreign keys on a three-way junction
# ---------------------------------------------------------------------------

def test_finding_with_unknown_body_unit_id_returns_unit_not_found(
    api, external_surveyor_headers
):
    """PRD §2.8: "Foreign keys supplied in a request body are resolved only after every path identifier has resolved."

    PRD §2.8: "A missing `unit_id` yields `ERR_UNIT_NOT_FOUND`, a missing `chapter_id` yields `ERR_CHAPTER_NOT_FOUND`, and a missing `standard_id` yields `ERR_STANDARD_NOT_FOUND`."

    PRD §3.7: "A finding names the `standard_id` found non-compliant and the `unit_id` where the non-compliance was observed, and quantifies the observation with `observed_noncompliance_count` non-compliant elements out of `sampled_count` elements sampled, plus an optional `patient_harm_observed` flag that defaults to false."

    Design: Corner/entities/finding_body_foreign_keys_unknown_unit_not_found
    """
    built = _setup_active_survey_with_standard()

    response = api.create_finding(
        built["window"]["id"],
        {
            "standard_id": built["standard"]["id"],
            "unit_id": "44444444-4444-4444-8444-444444444444",
            "observed_noncompliance_count": 2,
            "sampled_count": 10,
            "patient_harm_observed": False,
        },
        external_surveyor_headers,
    )
    validate_error(response, ApiErrorId.ERR_UNIT_NOT_FOUND)

    rows, meta = validate_paginated(
        api.list_findings(
            external_surveyor_headers, {"survey_window_id": built["window"]["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert rows == []
