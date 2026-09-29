"""Identifier resolution, pagination bounds, uniqueness guards, the clock echo and
version bookkeeping across entity families."""

from datetime import datetime

import pytest

from test_helpers import (
    DEFAULT_CLOCK_RENDERED,
    DIRECTOR_USER_ID,
    EXTERNAL_SURVEYOR_USER_ID,
    SAFETY_USER_ID,
    SURVEYOR_USER_ID,
    UNKNOWN_UUIDS,
    VALIDATOR_USER_ID,
    ApiErrorId,
    assign_owner,
    create_chapter,
    create_standard,
    create_unit,
    make_role_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def _instant_equals(actual, expected_iso: str) -> bool:
    """Compare two ISO 8601 UTC instants by value, tolerating the rendering."""
    if not isinstance(actual, str):
        return False
    return datetime.fromisoformat(actual.replace("Z", "+00:00")) == datetime.fromisoformat(
        expected_iso.replace("Z", "+00:00")
    )


def _setup_owned_standard(chapter_code: str = "IC", weight_pct: float = 50):
    """Chapter with one standard owned by owner-1 as PRIMARY."""
    chapter = create_chapter(chapter_code, "Infection Control", weight_pct, 1)
    standard = create_standard(
        chapter["id"], f"{chapter_code}.01.01.01", "Hand hygiene program", "DIRECT_IMPACT"
    )
    assignment = assign_owner(standard["id"], "owner-1", "PRIMARY")
    return {"chapter": chapter, "standard": standard, "assignment": assignment}


# ---------------------------------------------------------------------------
# Path and body identifier resolution
# ---------------------------------------------------------------------------

NOT_FOUND_FAMILIES = [
    ("GET", f"/accreditation/chapters/{UNKNOWN_UUIDS['chapter']}", None,
     DIRECTOR_USER_ID, "AccreditationDirector", ApiErrorId.ERR_CHAPTER_NOT_FOUND),
    ("GET", f"/accreditation/standards/{UNKNOWN_UUIDS['standard']}", None,
     DIRECTOR_USER_ID, "AccreditationDirector", ApiErrorId.ERR_STANDARD_NOT_FOUND),
    ("POST", f"/accreditation/owner-assignments/{UNKNOWN_UUIDS['owner_assignment']}/revoke",
     {"reason": "Unknown assignment"},
     DIRECTOR_USER_ID, "AccreditationDirector", ApiErrorId.ERR_OWNER_ASSIGNMENT_NOT_FOUND),
    ("GET", f"/accreditation/evidence-items/{UNKNOWN_UUIDS['evidence']}", None,
     VALIDATOR_USER_ID, "EvidenceValidator", ApiErrorId.ERR_EVIDENCE_NOT_FOUND),
    ("GET", f"/accreditation/units/{UNKNOWN_UUIDS['unit']}", None,
     DIRECTOR_USER_ID, "AccreditationDirector", ApiErrorId.ERR_UNIT_NOT_FOUND),
    ("GET", f"/accreditation/mock-tracers/{UNKNOWN_UUIDS['tracer']}", None,
     SURVEYOR_USER_ID, "TracerSurveyor", ApiErrorId.ERR_TRACER_NOT_FOUND),
    ("GET", f"/accreditation/rounding-sessions/{UNKNOWN_UUIDS['rounding_session']}", None,
     SAFETY_USER_ID, "SafetyOfficer", ApiErrorId.ERR_ROUNDING_SESSION_NOT_FOUND),
    ("GET", f"/accreditation/deficiency-tickets/{UNKNOWN_UUIDS['ticket']}", None,
     SAFETY_USER_ID, "SafetyOfficer", ApiErrorId.ERR_TICKET_NOT_FOUND),
    ("GET", f"/accreditation/survey-windows/{UNKNOWN_UUIDS['survey_window']}", None,
     DIRECTOR_USER_ID, "AccreditationDirector", ApiErrorId.ERR_SURVEY_WINDOW_NOT_FOUND),
    ("GET", f"/accreditation/survey-findings/{UNKNOWN_UUIDS['finding']}", None,
     EXTERNAL_SURVEYOR_USER_ID, "ExternalSurveyor", ApiErrorId.ERR_FINDING_NOT_FOUND),
    ("POST", f"/accreditation/ppr-self-assessments/{UNKNOWN_UUIDS['ppr']}/attest",
     {"attestation_note": "Unknown period"},
     DIRECTOR_USER_ID, "AccreditationDirector", ApiErrorId.ERR_PPR_NOT_FOUND),
]


@pytest.mark.parametrize(
    "method,path,payload,user_id,role,expected_error",
    NOT_FOUND_FAMILIES,
    ids=[case[5].value for case in NOT_FOUND_FAMILIES],
)
def test_each_addressable_family_returns_its_own_not_found_error_id(
    api, method, path, payload, user_id, role, expected_error
):
    """PRD §2.8: "The eleven not-found codes map one-to-one onto the eleven addressable resources: `ERR_CHAPTER_NOT_FOUND`, `ERR_STANDARD_NOT_FOUND`, `ERR_OWNER_ASSIGNMENT_NOT_FOUND`, `ERR_EVIDENCE_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_TRACER_NOT_FOUND`, `ERR_ROUNDING_SESSION_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_SURVEY_WINDOW_NOT_FOUND`, `ERR_FINDING_NOT_FOUND` and `ERR_PPR_NOT_FOUND`, all at HTTP 404."

    PRD §2.11: "5. Path existence, left to right — the eleven 404 codes of §2.8, on every endpoint with a path identifier."

    Design: Corner/errors/each_entity_family_not_found_returns_its_own_error_id
    """
    response = api.raw_request(method, path, payload, make_role_headers(user_id, role))
    error = validate_error(response, expected_error)

    assert response.status_code == 404
    assert response.json()["response_type"] == "error"
    assert error["message"].strip()


def test_unknown_path_session_outranks_unknown_body_standard_on_deficiency(
    api, safety_officer_headers
):
    """PRD §2.8: "Path identifiers are resolved strictly left to right, and the first identifier that does not resolve determines the rejection."

    PRD §2.8: "Foreign keys supplied in a request body are resolved only after every path identifier has resolved."

    PRD §2.11: "6. Body foreign-key existence for `unit_id`, `chapter_id` and `standard_id` — `ERR_UNIT_NOT_FOUND`, `ERR_CHAPTER_NOT_FOUND` or `ERR_STANDARD_NOT_FOUND`, 404, on `POST /accreditation/mock-tracers`, `POST /accreditation/rounding-sessions`, `POST /accreditation/mock-tracers/{id}/observations`, `POST /accreditation/rounding-sessions/{id}/deficiencies` and `POST /accreditation/survey-windows/{id}/findings`."

    Design: Corner/errors/path_id_not_found_precedes_body_foreign_key_not_found
    """
    response = api.create_deficiency(
        "22222222-2222-4222-8222-222222222201",
        {
            "standard_id": "22222222-2222-4222-8222-222222222202",
            "description": "Blocked corridor",
            "severity": "MODERATE",
        },
        safety_officer_headers,
    )
    validate_error(response, ApiErrorId.ERR_ROUNDING_SESSION_NOT_FOUND)

    rows, meta = validate_paginated(api.list_deficiency_tickets(safety_officer_headers))
    assert meta["total_count"] == 0
    assert rows == []


def test_unknown_body_chapter_on_tracer_scheduling_outranks_chapter_mapping_rule(
    api, tracer_surveyor_headers, director_headers
):
    """PRD §2.11: "6. Body foreign-key existence for `unit_id`, `chapter_id` and `standard_id` — `ERR_UNIT_NOT_FOUND`, `ERR_CHAPTER_NOT_FOUND` or `ERR_STANDARD_NOT_FOUND`, 404, on `POST /accreditation/mock-tracers`, `POST /accreditation/rounding-sessions`, `POST /accreditation/mock-tracers/{id}/observations`, `POST /accreditation/rounding-sessions/{id}/deficiencies` and `POST /accreditation/survey-windows/{id}/findings`."

    PRD §2.11: "44. The tracer's chapter has a `mapped_standard_count` of at least 1 — `ERR_CHAPTER_NOT_MAPPED`, 422, on `POST /accreditation/mock-tracers`."

    PRD §2.8: "A missing `unit_id` yields `ERR_UNIT_NOT_FOUND`, a missing `chapter_id` yields `ERR_CHAPTER_NOT_FOUND`, and a missing `standard_id` yields `ERR_STANDARD_NOT_FOUND`."

    Design: Corner/errors/body_foreign_key_not_found_precedes_chapter_mapping_rule
    """
    unit = create_unit("MED-13", "MED_SURG", 20)

    response = api.create_mock_tracer(
        {
            "unit_id": unit["id"],
            "chapter_id": "33333333-3333-4333-8333-333333333301",
            "tracer_type": "SYSTEM",
            "window_start": "2026-08-20T08:00:00Z",
            "window_end": "2026-08-20T10:00:00Z",
            "expected_unit_version": unit["version"],
        },
        tracer_surveyor_headers,
    )
    validate_error(response, ApiErrorId.ERR_CHAPTER_NOT_FOUND)

    reread = validate_success(api.get_unit(unit["id"], director_headers))
    assert reread["version"] == unit["version"]
    assert reread["scheduled_tracer_count"] == 0


# ---------------------------------------------------------------------------
# Pagination bounds
# ---------------------------------------------------------------------------

def test_deficiency_ticket_listing_with_limit_zero_returns_invalid_pagination(
    api, safety_officer_headers
):
    """PRD §2.3: "A `limit` outside the inclusive range 1 through 100, or a negative `offset`, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."

    PRD §2.11: "4. Pagination bounds: `limit` within 1 through 100 inclusive and `offset` at least 0 — `ERR_INVALID_PAGINATION`, 400, on every collection read."

    Design: Corner/validations/pagination_limit_zero_returns_invalid_pagination
    """
    response = api.list_deficiency_tickets(safety_officer_headers, {"limit": 0, "offset": 0})
    validate_error(response, ApiErrorId.ERR_INVALID_PAGINATION)


# ---------------------------------------------------------------------------
# Uniqueness and accountability guards
# ---------------------------------------------------------------------------

def test_second_chapter_with_same_code_returns_duplicate_resource(api, director_headers):
    """PRD §3.1: "A colliding `code` is rejected with `ERR_DUPLICATE_RESOURCE`."

    PRD §2.11: "11. Uniqueness of `Chapter.code`, `HospitalUnit.name`, `SurveyWindow.cycle_label`, the pair of chapter and `standard_code`, and the pair of chapter and `period_label` — `ERR_DUPLICATE_RESOURCE`, 409, on `POST /accreditation/chapters`, `POST /accreditation/units`, `POST /accreditation/survey-windows`, `POST /accreditation/chapters/{id}/standards` and `POST /accreditation/chapters/{id}/ppr-self-assessments`."

    Design: Corner/validations/duplicate_chapter_code_returns_duplicate_resource
    """
    first = create_chapter("EC", "Environment of Care", 60, 1)

    response = api.create_chapter(
        {"code": "EC", "name": "Environment of Care (revised)", "weight_pct": 40,
         "evidence_min_count": 2},
        director_headers,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_RESOURCE)

    reread = validate_success(api.get_chapter(first["id"], director_headers))
    assert float(reread["weight_pct"]) == 60
    assert reread["name"] == "Environment of Care"
    assert reread["evidence_min_count"] == 1


def test_same_owner_twice_on_one_standard_returns_duplicate_owner_assignment(
    api, director_headers
):
    """PRD §3.1: "If the same `owner_user_id` already holds an `ACTIVE` assignment on that standard, the request is rejected with `ERR_DUPLICATE_OWNER_ASSIGNMENT`; two distinct owners on one standard, or the same owner on two standards, are both fine."

    PRD §2.11: "39. No owner assignment with the same `owner_user_id` and `status` `ACTIVE` already exists on this standard — `ERR_DUPLICATE_OWNER_ASSIGNMENT`, 409, on `POST /accreditation/standards/{id}/owner-assignments`."

    PRD §3.1: "The standard's `active_owner_count` increases by one."

    Design: Corner/validations/duplicate_active_owner_assignment_rejected
    """
    built = _setup_owned_standard()

    response = api.create_owner_assignment(
        built["standard"]["id"],
        {"owner_user_id": "owner-1", "designation": "SECONDARY"},
        director_headers,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_OWNER_ASSIGNMENT)

    standard = validate_success(api.get_standard(built["standard"]["id"], director_headers))
    assert standard["active_owner_count"] == 1
    assert standard["compliance_state"] == "MAPPED"

    rows, meta = validate_paginated(
        api.list_owner_assignments(built["standard"]["id"], director_headers)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == built["assignment"]["id"]
    assert rows[0]["designation"] == "PRIMARY"
    assert rows[0]["status"] == "ACTIVE"


def test_revoking_an_already_revoked_assignment_is_rejected(api, director_headers):
    """PRD §3.1: "The `AccreditationDirector` revokes an assignment, optionally recording a `reason`, and the assignment must still be `ACTIVE` or the request is rejected with `ERR_OWNER_ASSIGNMENT_ALREADY_REVOKED`."

    PRD §3.1: "Revocation sets `status` to `REVOKED` and stamps `revoked_at` with the current logical clock, then decreases the standard's `active_owner_count` by one."

    PRD §3.1: "From `MAPPED`, the standard returns to `UNMAPPED` and the chapter's `mapped_standard_count` decreases by one."

    PRD §2.4: "The server maintains a **logical clock** that begins at the fixed instant `2026-08-01T00:00:00Z` and never falls back to real time; every deadline, window boundary, expiry and "current instant" in this specification means the value of that logical clock at the moment the request is processed."

    Design: Corner/validations/revoke_already_revoked_owner_assignment_rejected
    """
    built = _setup_owned_standard()
    assignment_id = built["assignment"]["id"]

    revoked = validate_success(
        api.revoke_owner_assignment(
            assignment_id, {"reason": "Owner left the organisation"}, director_headers
        )
    )
    assert revoked["status"] == "REVOKED"
    assert revoked["revoked_at"] == DEFAULT_CLOCK_RENDERED

    response = api.revoke_owner_assignment(
        assignment_id, {"reason": "Duplicate request"}, director_headers
    )
    validate_error(response, ApiErrorId.ERR_OWNER_ASSIGNMENT_ALREADY_REVOKED)

    standard = validate_success(api.get_standard(built["standard"]["id"], director_headers))
    assert standard["active_owner_count"] == 0
    assert standard["compliance_state"] == "UNMAPPED"

    chapter = validate_success(api.get_chapter(built["chapter"]["id"], director_headers))
    assert chapter["mapped_standard_count"] == 0


# ---------------------------------------------------------------------------
# The logical clock echo
# ---------------------------------------------------------------------------

def test_clock_advance_on_empty_database_reports_zero_sweep_counts(api, director_headers):
    """PRD §2.4: "The response to that call reports the resulting `current_utc`, together with `expired_evidence_count` and `eligible_window_count` describing what the advance swept."

    PRD §2.4: "`expired_evidence_count` is the number of evidence items expired by the sweep and `eligible_window_count` is the number of windows that became eligible."

    Design: Corner/endpoints/clock_endpoint_returns_zero_counts_when_nothing_due
    """
    first = validate_success(api.set_clock("2027-01-01T00:00:00Z", director_headers))
    assert _instant_equals(first["current_utc"], "2027-01-01T00:00:00Z")
    assert first["expired_evidence_count"] == 0
    assert first["eligible_window_count"] == 0

    again = validate_success(api.set_clock("2027-01-01T00:00:00Z", director_headers))
    assert _instant_equals(again["current_utc"], "2027-01-01T00:00:00Z")
    assert again["expired_evidence_count"] == 0
    assert again["eligible_window_count"] == 0


# ---------------------------------------------------------------------------
# Version bookkeeping across entity families
# ---------------------------------------------------------------------------

def test_version_increments_on_every_write_across_entities(
    api, director_headers, tracer_surveyor_headers, safety_officer_headers
):
    """PRD §2.5: "Most resources additionally carry `updated_at`, an ISO 8601 UTC instant in the same format that is refreshed on every mutation, and `version`, an integer that starts at 1 when the resource is created and increases by one on every mutation of that resource."

    PRD §3.4: "It also increments the unit's `scheduled_tracer_count` by one and advances the unit's `version` — which is precisely why a client scheduling two tracers back to back must re-read the unit between them."

    PRD §3.4: "Starting stamps `started_at` with the current logical clock, decrements the unit's `scheduled_tracer_count` by one, recomputes the unit's readiness, and advances the tracer's `version`."

    PRD §3.5: "The `SafetyOfficer` closes it, the server requires that no ticket of that session sits in `ESCALATED` — otherwise the request is rejected with `ERR_ESCALATED_TICKET_BLOCKS_CLOSE` — and on success the session moves `OPEN → CLOSED` with `closed_at` stamped from the logical clock and its `version` advanced."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_write_across_entities
    """
    chapter = create_chapter("EC", "Environment of Care", 100, 1)
    standard = create_standard(chapter["id"], "EC.02.06.01", "Safe environment", "DIRECT_IMPACT")
    assign_owner(standard["id"], "owner-1", "PRIMARY")
    unit = create_unit("ICU-17", "ICU", 12)
    unit_version_before = unit["version"]

    tracer = validate_success(
        api.create_mock_tracer(
            {
                "unit_id": unit["id"],
                "chapter_id": chapter["id"],
                "tracer_type": "PATIENT",
                "window_start": "2026-08-20T08:00:00Z",
                "window_end": "2026-08-20T12:00:00Z",
                "expected_unit_version": unit_version_before,
            },
            tracer_surveyor_headers,
        ),
        201,
    )
    assert tracer["version"] == 1

    unit_after_schedule = validate_success(api.get_unit(unit["id"], director_headers))
    assert unit_after_schedule["version"] == unit_version_before + 1
    assert unit_after_schedule["scheduled_tracer_count"] == 1

    set_clock("2026-08-20T09:00:00Z")
    started = validate_success(
        api.transition_mock_tracer(tracer["id"], {"action": "START"}, tracer_surveyor_headers)
    )
    assert started["version"] == tracer["version"] + 1

    session = validate_success(
        api.create_rounding_session(
            {
                "unit_id": unit["id"],
                "round_type": "LIFE_SAFETY",
                "window_start": "2026-08-20T13:00:00Z",
                "window_end": "2026-08-20T15:00:00Z",
            },
            safety_officer_headers,
        ),
        201,
    )
    assert session["version"] == 1

    closed = validate_success(
        api.close_rounding_session(session["id"], {}, safety_officer_headers)
    )
    assert closed["state"] == "CLOSED"
    assert closed["version"] == 2
