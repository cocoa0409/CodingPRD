"""Role authorization and the one entity-backed identity in the system: the 401
of a missing header against the 403 of a forbidden role, the director-exclusive
and surveyor-exclusive writes, and the `UnitManager` whose `X-User-ID` is a
hospital unit id and whose reach stops at its own unit's tickets."""

from test_helpers import (
    ApiErrorId,
    assign_owner,
    close_rounding_session,
    create_chapter,
    create_standard,
    create_unit,
    headers_without_user_id,
    make_role_headers,
    make_unit_manager_headers,
    open_rounding_session,
    raise_deficiency,
    read_unit,
    validate_error,
    validate_success,
)

CHAPTER_PAYLOAD = {
    "code": "EC",
    "name": "Environment of Care",
    "weight_pct": 100,
    "evidence_min_count": 1,
}


# ---------------------------------------------------------------------------
# Private setup chains — every test rebuilds its own world from scratch.
# ---------------------------------------------------------------------------

def _setup_mapped_standard():
    """Chapter EC with one standard held by an ACTIVE PRIMARY owner."""
    chapter = create_chapter("EC", "Environment of Care", 100, 1)
    standard = create_standard(
        chapter["id"], "EC.02.06.01", "Safe environment", "DIRECT_IMPACT"
    )
    assign_owner(standard["id"], "owner-1", "PRIMARY")
    return {"chapter": chapter, "standard": standard}


def _setup_open_ticket_on_unit(unit_name="ICU-14", unit_type="ICU", bed_count=12):
    """One OPEN MODERATE ticket on a rounding session of the named unit."""
    built = _setup_mapped_standard()
    unit = create_unit(unit_name, unit_type, bed_count)
    session = open_rounding_session(
        unit["id"],
        "ENVIRONMENT_OF_CARE",
        "2026-08-01T08:00:00Z",
        "2026-08-01T12:00:00Z",
    )
    ticket = raise_deficiency(
        session["id"], built["standard"]["id"], "MODERATE", "Missing eyewash signage"
    )
    built.update({"unit": unit, "session": session, "ticket": ticket})
    return built


# ---------------------------------------------------------------------------
# rbac / chapter_create_missing_x_user_id_header_returns_unauthenticated
# ---------------------------------------------------------------------------

def test_chapter_creation_without_x_user_id_header_is_unauthenticated(
    api, director_headers
):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role that principal is acting in."
    PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the seven declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.11: "1. Authentication: `X-User-Role` and `X-User-ID` are present and `X-User-Role` names a declared role — `ERR_UNAUTHENTICATED`, 401, on every endpoint."

    Design: Corner/rbac/chapter_create_missing_x_user_id_header_returns_unauthenticated
    """
    error = validate_error(
        api.raw_request(
            "POST",
            "/accreditation/chapters",
            dict(CHAPTER_PAYLOAD),
            headers_without_user_id("AccreditationDirector"),
        ),
        ApiErrorId.ERR_UNAUTHENTICATED,
    )
    assert isinstance(error["message"], str) and error["message"].strip()

    validate_error(
        api.create_chapter(
            dict(CHAPTER_PAYLOAD), make_role_headers("dir-1", "ChiefOfStaff")
        ),
        ApiErrorId.ERR_UNAUTHENTICATED,
    )

    # Neither rejected request created a chapter, so the code is still free.
    created = validate_success(
        api.create_chapter(dict(CHAPTER_PAYLOAD), director_headers), 201
    )
    assert created["code"] == "EC"


# ---------------------------------------------------------------------------
# rbac / standard_owner_cannot_create_chapter_returns_unauthorized
# ---------------------------------------------------------------------------

def test_standard_owner_creating_a_chapter_is_unauthorized(
    api, standard_owner_headers, director_headers
):
    """PRD §2.1: "If the headers are well formed but the named role is not permitted to perform the requested operation — including the case where the role is permitted on the endpoint generally but not for the specific `action` or `decision` value supplied in the body — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "This is the only role that may register chapters, standards, owner assignments, revocations, hospital units and survey windows, drive survey-window transitions, file, revise and attest periodic performance review self-assessments, and advance the server's logical clock."

    Design: Corner/rbac/standard_owner_cannot_create_chapter_returns_unauthorized
    """
    validate_error(
        api.create_chapter(dict(CHAPTER_PAYLOAD), standard_owner_headers),
        ApiErrorId.ERR_UNAUTHORIZED,
    )

    # No chapter row was created, so the same code is not a duplicate afterwards.
    created = validate_success(
        api.create_chapter(dict(CHAPTER_PAYLOAD), director_headers), 201
    )
    assert created["code"] == "EC"


# ---------------------------------------------------------------------------
# rbac / safety_officer_cannot_schedule_tracer_returns_unauthorized
# ---------------------------------------------------------------------------

def test_safety_officer_scheduling_a_mock_tracer_is_unauthorized(
    api, safety_officer_headers, tracer_surveyor_headers
):
    """PRD §2.1: "If the headers are well formed but the named role is not permitted to perform the requested operation — including the case where the role is permitted on the endpoint generally but not for the specific `action` or `decision` value supplied in the body — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.4: "Scheduling one is open to both the `TracerSurveyor` and the `AccreditationDirector`, and the payload names the `unit_id` to be traced, the `chapter_id` whose standards will be sampled, a `tracer_type` of `PATIENT`, `SYSTEM` or `INDIVIDUAL`, a half-open occupation interval given as `window_start` and `window_end`, and the stale-view guard `expected_unit_version` described in §2.7."
    PRD §3.4: "It also increments the unit's `scheduled_tracer_count` by one and advances the unit's `version` — which is precisely why a client scheduling two tracers back to back must re-read the unit between them."

    Design: Corner/rbac/safety_officer_cannot_schedule_tracer_returns_unauthorized
    """
    built = _setup_mapped_standard()
    unit = create_unit("ED-13", "ED", 18)
    payload = {
        "unit_id": unit["id"],
        "chapter_id": built["chapter"]["id"],
        "tracer_type": "SYSTEM",
        "window_start": "2026-08-20T08:00:00Z",
        "window_end": "2026-08-20T10:00:00Z",
        "expected_unit_version": unit["version"],
    }

    validate_error(
        api.create_mock_tracer(dict(payload), safety_officer_headers),
        ApiErrorId.ERR_UNAUTHORIZED,
    )

    after = read_unit(unit["id"])
    assert after["scheduled_tracer_count"] == 0
    assert after["version"] == unit["version"]

    # Only the role differed: the identical payload as TracerSurveyor succeeds.
    tracer = validate_success(
        api.create_mock_tracer(dict(payload), tracer_surveyor_headers), 201
    )
    assert tracer["state"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# rbac / unit_manager_cannot_transition_another_units_ticket
# ---------------------------------------------------------------------------

def test_unit_manager_starting_work_on_another_units_ticket_violates_unit_scope(
    api, director_headers
):
    """PRD §2.1: "When `X-User-Role` is `UnitManager`, by contrast, `X-User-ID` is the `id` of the acting `HospitalUnit`; ownership checks on a deficiency ticket compare the `unit_id` of the ticket's rounding session to `X-User-ID`, and a mismatch is rejected with `ERR_UNIT_SCOPE_VIOLATION` (HTTP 403)."
    PRD §3.5: "Throughout all five actions, a `UnitManager` is confined to its own unit: if `X-User-ID` does not equal the `id` of the `HospitalUnit` reached through the ticket's rounding session, the request is refused with `ERR_UNIT_SCOPE_VIOLATION`."
    PRD §2.11: "7. Unit scoping: when `X-User-Role` is `UnitManager`, `X-User-ID` equals the `id` of the `HospitalUnit` reached through the ticket's rounding session — `ERR_UNIT_SCOPE_VIOLATION`, 403, on `POST /accreditation/deficiency-tickets/{id}/transition`."

    Design: Corner/rbac/unit_manager_cannot_transition_another_units_ticket
    """
    built = _setup_open_ticket_on_unit()
    other_unit = create_unit("MED-14", "MED_SURG", 24)
    ticket = built["ticket"]
    assert ticket["state"] == "OPEN"

    validate_error(
        api.transition_deficiency_ticket(
            ticket["id"],
            {"action": "START_WORK", "note": "Wrong unit manager"},
            make_unit_manager_headers(other_unit["id"]),
        ),
        ApiErrorId.ERR_UNIT_SCOPE_VIOLATION,
    )

    after = validate_success(api.get_deficiency_ticket(ticket["id"], director_headers))
    assert after["state"] == "OPEN"
    assert after["version"] == ticket["version"]

    unit = read_unit(built["unit"]["id"])
    assert unit["open_deficiency_penalty_points"] == 3


# ---------------------------------------------------------------------------
# rbac / unit_manager_can_start_work_on_own_unit_ticket
# ---------------------------------------------------------------------------

def test_unit_manager_can_start_work_on_a_ticket_of_its_own_unit(api):
    """PRD §3.5: "`START_WORK` moves a ticket `OPEN → IN_PROGRESS` with no precondition and advances its `version`; it is available to both a `SafetyOfficer` and a `UnitManager`."
    PRD §2.10: "A `UnitManager` may drive a deficiency ticket only through the `START_WORK` and `MARK_REMEDIATED` actions, and only for tickets whose rounding session belongs to the unit named by `X-User-ID`; the actions `VERIFY`, `FAIL_VERIFICATION` and `ESCALATE` are reserved to a `SafetyOfficer`, so that no unit signs off on its own remediation."
    PRD §2.9: "The **unit penalty ledger** pins `HospitalUnit.open_deficiency_penalty_points` to the sum of `penalty_points` over every deficiency ticket of that unit that has not reached `VERIFIED` — that is, every ticket in `OPEN`, `IN_PROGRESS`, `REMEDIATED` or `ESCALATED`."

    Design: Corner/rbac/unit_manager_can_start_work_on_own_unit_ticket
    """
    built = _setup_open_ticket_on_unit()
    manager = make_unit_manager_headers(built["unit"]["id"])
    assert built["ticket"]["penalty_points"] == 3

    started = validate_success(
        api.transition_deficiency_ticket(
            built["ticket"]["id"],
            {"action": "START_WORK", "note": "Signage ordered"},
            manager,
        )
    )
    assert started["state"] == "IN_PROGRESS"
    assert started["penalty_points"] == 3

    unit = validate_success(api.get_unit(built["unit"]["id"], manager))
    assert unit["open_deficiency_penalty_points"] == 3
    assert unit["posture"] == "OPEN"


# ---------------------------------------------------------------------------
# rbac / unit_manager_cannot_verify_own_unit_ticket_returns_unauthorized
# ---------------------------------------------------------------------------

def test_unit_manager_verifying_its_own_units_ticket_is_unauthorized(
    api, director_headers
):
    """PRD §3.5: "`VERIFY` moves a ticket `REMEDIATED → VERIFIED` and is reserved to the `SafetyOfficer` — a `UnitManager` attempting it is refused, since no unit may verify its own remediation."
    PRD §2.10: "A `UnitManager` may drive a deficiency ticket only through the `START_WORK` and `MARK_REMEDIATED` actions, and only for tickets whose rounding session belongs to the unit named by `X-User-ID`; the actions `VERIFY`, `FAIL_VERIFICATION` and `ESCALATE` are reserved to a `SafetyOfficer`, so that no unit signs off on its own remediation."
    PRD §2.11: "2. Authorization: the acting role may perform this operation, and on a multi-action endpoint the role is permitted for the requested action specifically (`SUBMIT` is `StandardOwner`-only, `VALIDATE` and `REJECT` are `EvidenceValidator`-only, `VERIFY`, `FAIL_VERIFICATION` and `ESCALATE` are `SafetyOfficer`-only) — `ERR_UNAUTHORIZED`, 403, on every endpoint."

    Design: Corner/rbac/unit_manager_cannot_verify_own_unit_ticket_returns_unauthorized
    """
    built = _setup_open_ticket_on_unit()
    manager = make_unit_manager_headers(built["unit"]["id"])
    ticket_id = built["ticket"]["id"]

    validate_success(
        api.transition_deficiency_ticket(
            ticket_id, {"action": "START_WORK", "note": "Signage ordered"}, manager
        )
    )
    remediated = validate_success(
        api.transition_deficiency_ticket(
            ticket_id, {"action": "MARK_REMEDIATED", "note": "Signage installed"}, manager
        )
    )
    assert remediated["state"] == "REMEDIATED"
    session = close_rounding_session(built["session"]["id"])
    assert session["state"] == "CLOSED"

    validate_error(
        api.transition_deficiency_ticket(
            ticket_id,
            {"action": "VERIFY", "note": "Self-verification attempt"},
            manager,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
    )

    after = validate_success(api.get_deficiency_ticket(ticket_id, director_headers))
    assert after["state"] == "REMEDIATED"
    assert after["verified_by_user_id"] is None

    unit = read_unit(built["unit"]["id"])
    assert unit["open_deficiency_penalty_points"] == 3


# ---------------------------------------------------------------------------
# rbac / unit_manager_shared_read_access_is_allowed
# ---------------------------------------------------------------------------

def test_unit_manager_may_read_a_chapter_and_a_unit_readiness(api):
    """PRD §2.1: "Every read operation in the system is available to all seven roles."
    PRD §3.3: "If no chapter participates, the computation stops immediately with `readiness_score` 0.00 and `readiness_band` `NOT_ASSESSED`, and the penalty is **not** applied — an unassessed unit is not punished for its open deficiencies."
    PRD §3.1: "A freshly registered chapter is an empty shell with every derived counter at zero — `standard_count`, `mapped_standard_count`, `evidence_complete_standard_count`, `deficient_standard_count` and `ppr_escalation_count` — and a `readiness_flag` of `ON_TRACK`."

    Design: Corner/rbac/unit_manager_shared_read_access_is_allowed
    """
    chapter = create_chapter("EC", "Environment of Care", 100, 1)
    unit = create_unit("ICU-15", "ICU", 12)
    manager = make_unit_manager_headers(unit["id"])

    read_chapter_data = validate_success(api.get_chapter(chapter["id"], manager))
    assert read_chapter_data["code"] == "EC"
    assert read_chapter_data["mapped_standard_count"] == 0

    readiness = validate_success(api.get_unit_readiness(unit["id"], manager))
    assert readiness["readiness_band"] == "NOT_ASSESSED"
