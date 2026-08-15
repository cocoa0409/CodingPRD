"""Registered-agent coverage claims: resignation notice lifecycle, coverage
continuity during the notice window, state gates, the RBAC split between
notice and finalization, and the depth-3 resignation cascade."""
from test_helpers import (
    ApiErrorId,
    SEC1,
    appoint_agent,
    appoint_officer,
    create_agent,
    create_agent_appointment_payload,
    create_draft_entity,
    create_jurisdiction_j1,
    create_officer,
    fetch_entity,
    fetch_entity_version,
    list_event_types,
    list_filings,
    make_agent_headers,
    make_officer_headers,
    set_clock,
    setup_base_entity,
    setup_entity_with_qualification,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client


def test_agent_finalize_unripe_rejected(api):
    """PRD 3.3: "Finalization is blocked until the current logical date is on
    or after `effective_end_date`; premature finalization is rejected with
    `ERR_AGENT_RESIGNATION_NOTICE_UNRIPE`."
    PRD 3.3: "This transitions the appointment from `ACTIVE` to
    `NOTICE_PENDING`, sets `notice_date` to the current logical date, and
    computes `effective_end_date` as `notice_date` plus the jurisdiction's
    `ra_resignation_notice_days`."

    Design: Corner/state_machines/agent_finalize_unripe_rejected
    """
    ctx = setup_base_entity(legal_name="Unripe Corp")
    entity, ag1 = ctx["entity"], ctx["agent"]
    aa1 = validate_paginated(
        api.list_agent_appointments(SEC1, params={"entity_id": entity["id"]})
    )[0][0]

    noticed = validate_success(
        api.file_resignation_notice(aa1["id"], make_agent_headers(ag1["id"]))
    )
    assert noticed["status"] == "NOTICE_PENDING"
    assert noticed["notice_date"] == "2026-08-01"
    assert noticed["effective_end_date"] == "2026-08-31", "notice date + 30 days"

    set_clock("2026-08-30T00:00:00Z")  # one day before the notice ripens
    response = api.finalize_resignation(aa1["id"], SEC1)
    validate_error(response, ApiErrorId.ERR_AGENT_RESIGNATION_NOTICE_UNRIPE)

    current = validate_success(api.get_agent_appointment(aa1["id"], SEC1))
    assert current["status"] == "NOTICE_PENDING"


def test_appointment_and_agent_state_gate_errors(api):
    """PRD 3.3: "Only one `ACTIVE` appointment may exist per entity and
    jurisdiction. A second appointment that overlaps an `ACTIVE` incumbent
    outside a notice window is rejected with `ERR_AGENT_APPOINTMENT_OVERLAP`."
    PRD 3.3: "Attempting to finalize a non-`NOTICE_PENDING` appointment is
    rejected with `ERR_AGENT_APPOINTMENT_NOT_NOTICE_PENDING`."
    PRD 3.5: "A resignation attempt on a non-`APPOINTED` appointment is
    rejected with `ERR_APPOINTMENT_NOT_APPOINTED`."
    PRD 3.3: "Attempting to file notice on a non-`ACTIVE` appointment is
    rejected with `ERR_AGENT_APPOINTMENT_NOT_ACTIVE`."

    Design: Corner/errors/appointment_and_agent_state_gate_errors
    """
    ctx = setup_base_entity(legal_name="Gates3 Corp")
    entity, ag1, j1 = ctx["entity"], ctx["agent"], ctx["jurisdiction"]
    aa1 = validate_paginated(
        api.list_agent_appointments(SEC1, params={"entity_id": entity["id"]})
    )[0][0]
    officer = create_officer()
    appointment = appoint_officer(entity["id"], officer["id"])

    # Overlapping second appointment while the incumbent is plain ACTIVE.
    overlap = api.create_agent_appointment(
        entity["id"],
        create_agent_appointment_payload(ag1["id"], j1["id"], start_date="2026-01-01"),
        SEC1,
    )
    validate_error(overlap, ApiErrorId.ERR_AGENT_APPOINTMENT_OVERLAP)

    # Finalize without a notice on file.
    premature = api.finalize_resignation(aa1["id"], SEC1)
    validate_error(premature, ApiErrorId.ERR_AGENT_APPOINTMENT_NOT_NOTICE_PENDING)

    # Holder resigns; a second resignation hits the state gate.
    resigned = validate_success(
        api.resign_officer_appointment(appointment["id"], make_officer_headers(officer["id"]))
    )
    assert resigned["status"] == "RESIGNED"
    double_resign = api.resign_officer_appointment(
        appointment["id"], make_officer_headers(officer["id"])
    )
    validate_error(double_resign, ApiErrorId.ERR_APPOINTMENT_NOT_APPOINTED)

    # Notice filed; a second notice hits the state gate.
    noticed = validate_success(
        api.file_resignation_notice(aa1["id"], make_agent_headers(ag1["id"]))
    )
    assert noticed["status"] == "NOTICE_PENDING"
    double_notice = api.file_resignation_notice(aa1["id"], make_agent_headers(ag1["id"]))
    validate_error(double_notice, ApiErrorId.ERR_AGENT_APPOINTMENT_NOT_ACTIVE)


def test_agent_user_cannot_finalize_resignation(api):
    """PRD 4: POST /api/agent-appointments/{appointmentId}/finalize-resignation
    is authorized for CorporateSecretary only.
    PRD 2.1: "A request whose role is not permitted for the target endpoint is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/agent_user_cannot_finalize_resignation
    """
    j1 = create_jurisdiction_j1()
    ag1 = create_agent(j1["id"])
    entity = create_draft_entity(j1["id"], legal_name="Agentrole Corp", authorized_shares=None)
    aa1 = appoint_agent(entity["id"], ag1["id"], j1["id"])
    noticed = validate_success(
        api.file_resignation_notice(aa1["id"], make_agent_headers(ag1["id"]))
    )
    assert noticed["status"] == "NOTICE_PENDING"

    # Even the appointment's own agent may not finalize: notice and
    # finalization are held apart by role.
    response = api.finalize_resignation(aa1["id"], make_agent_headers(ag1["id"]))
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)

    current = validate_success(api.get_agent_appointment(aa1["id"], SEC1))
    assert current["status"] == "NOTICE_PENDING"


def test_agent_coverage_continuity_gap_rejected(api):
    """PRD 3.3: "When an incumbent is in `NOTICE_PENDING`, a successor
    appointment's `start_date` must be on or before the incumbent's
    `effective_end_date`; otherwise the request is rejected with
    `ERR_AGENT_COVERAGE_GAP`."
    PRD 3.3: "computes `effective_end_date` as `notice_date` plus the
    jurisdiction's `ra_resignation_notice_days`."

    Design: Difficulty/resource_temporal_overlap/agent_coverage_continuity
    """
    ctx = setup_base_entity(legal_name="Coverage Corp")
    entity, ag1, j1 = ctx["entity"], ctx["agent"], ctx["jurisdiction"]
    aa1 = validate_paginated(
        api.list_agent_appointments(SEC1, params={"entity_id": entity["id"]})
    )[0][0]

    noticed = validate_success(
        api.file_resignation_notice(aa1["id"], make_agent_headers(ag1["id"]))
    )
    assert noticed["effective_end_date"] == "2026-08-31", "notice 2026-08-01 + 30 days"

    # A successor starting after the incumbent's effective end leaves uncovered
    # days — the gap is forbidden.
    gap = api.create_agent_appointment(
        entity["id"],
        create_agent_appointment_payload(ag1["id"], j1["id"], start_date="2026-09-01"),
        SEC1,
    )
    validate_error(gap, ApiErrorId.ERR_AGENT_COVERAGE_GAP)


def test_agent_coverage_continuity_overlap_accepted(api):
    """PRD 3.3: "When an incumbent is in `NOTICE_PENDING`, a successor
    appointment's `start_date` must be on or before the incumbent's
    `effective_end_date`; otherwise the request is rejected with
    `ERR_AGENT_COVERAGE_GAP`."

    Design: Difficulty/resource_temporal_overlap/agent_coverage_continuity
    """
    ctx = setup_base_entity(legal_name="Coverage Corp")
    entity, ag1, j1 = ctx["entity"], ctx["agent"], ctx["jurisdiction"]
    aa1 = validate_paginated(
        api.list_agent_appointments(SEC1, params={"entity_id": entity["id"]})
    )[0][0]
    validate_success(api.file_resignation_notice(aa1["id"], make_agent_headers(ag1["id"])))

    # A successor starting inside the notice window overlaps the incumbent —
    # that overlap is exactly what the continuity rule requires.
    successor = validate_success(
        api.create_agent_appointment(
            entity["id"],
            create_agent_appointment_payload(ag1["id"], j1["id"], start_date="2026-08-27"),
            SEC1,
        ),
        201,
    )
    assert successor["status"] == "ACTIVE"

    rows, meta = validate_paginated(
        api.list_agent_appointments(
            SEC1, params={"entity_id": entity["id"], "jurisdiction_id": j1["id"]}
        )
    )
    assert meta["total_count"] == 2, "incumbent NOTICE_PENDING + successor ACTIVE"


def _setup_resignation_cascade():
    """ACTIVE entity qualified in J3, with the J3 resignation notice filed and
    the clock advanced to the ripe date (2026-08-31)."""
    ctx = setup_entity_with_qualification(confirm=True)
    aa3, ag3 = ctx["aa3"], ctx["ag3"]
    noticed = validate_success(
        api_client.file_resignation_notice(aa3["id"], make_agent_headers(ag3["id"]))
    )
    assert noticed["effective_end_date"] == "2026-08-31"
    set_clock("2026-08-31T00:00:00Z")
    return ctx


def test_agent_resignation_cascade_revokes_qualification_and_filings(api):
    """PRD 3.3: "Upon finalization, the system appends a `ComplianceEvent` of
    type `AGENT_RESIGNED`, recomputes the entity's `compliance_posture`,
    revokes every `ForeignQualification` in that jurisdiction whose status is
    `QUALIFIED`, withdraws those qualifications' `SCHEDULED` or `PREPARED`
    filings, and increments the entity's `version`."
    PRD 3.8: "Revocation transitions the qualification to `REVOKED`, appends a
    `ComplianceEvent` of type `QUALIFICATION_REVOKED`, and withdraws its future
    filings."

    Design: Difficulty/transitive_cascade/agent_resignation_cascade
    """
    ctx = _setup_resignation_cascade()
    entity, j3, aa3, qualification = (
        ctx["entity"],
        ctx["j3"],
        ctx["aa3"],
        ctx["qualification"],
    )

    finalized = validate_success(api.finalize_resignation(aa3["id"], SEC1))
    assert finalized["status"] == "RESIGNED"

    revoked = validate_success(api.get_qualification(qualification["id"], SEC1))
    assert revoked["status"] == "REVOKED", "hop 2: coverage loss revokes the qualification"

    j3_filings = list_filings(entity["id"], jurisdiction_id=j3["id"])
    assert len(j3_filings) == 1
    assert j3_filings[0]["status"] == "WITHDRAWN", (
        "hop 3: the revoked qualification's future filings withdraw"
    )

    event_types = list_event_types(entity["id"])
    assert "AGENT_RESIGNED" in event_types
    assert "QUALIFICATION_REVOKED" in event_types
    assert "FILING_WITHDRAWN" in event_types


def test_agent_resignation_cascade_posture_recovers(api):
    """PRD 3.13: "The registered jurisdictions of an entity are its formation
    jurisdiction while the entity is `ACTIVE` or `DISSOLUTION_PENDING`, plus
    the jurisdictions of its qualifications in `PENDING`, `QUALIFIED`, or
    `WITHDRAWAL_PENDING` status."
    PRD 3.13: "If neither condition holds, `suspended_since` is cleared, and
    posture is `DELINQUENT` if any filing is `OVERDUE`, else `GOOD_STANDING`."
    PRD 3.3: "and increments the entity's `version`."

    Design: Difficulty/transitive_cascade/agent_resignation_cascade
    """
    ctx = _setup_resignation_cascade()
    entity, aa3 = ctx["entity"], ctx["aa3"]
    version_before = fetch_entity_version(entity["id"])

    validate_success(api.finalize_resignation(aa3["id"], SEC1))

    current = fetch_entity(entity["id"])
    # The REVOKED qualification leaves the registered set, so the uncovered J3
    # no longer counts; J1 coverage remains intact.
    assert current["compliance_posture"] == "GOOD_STANDING"
    assert current["suspended_since"] is None
    assert current["version"] == version_before + 1, "finalization increments the version"
