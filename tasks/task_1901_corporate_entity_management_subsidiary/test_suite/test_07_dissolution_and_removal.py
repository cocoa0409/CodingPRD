"""Dissolution and officer-removal claims: the terminal lockdown, the open
qualification gate, the REMOVE_OFFICER materialization cascade, and the
depth-3 dissolution compensation cascade."""
from test_helpers import (
    ApiErrorId,
    SEC1,
    adopt_resolution,
    appoint_officer,
    create_grant,
    create_officer,
    fetch_entity,
    find_officer_appointment,
    list_event_types,
    list_filings,
    run_sweep,
    setup_base_entity,
    setup_entity_with_qualification,
    validate_error,
    validate_success,
)


def test_dissolved_entity_terminal_lockdown(api):
    """PRD 3.12: "Attempting to commence dissolution on a non-`ACTIVE` entity is
    rejected with `ERR_ENTITY_NOT_ACTIVE`."
    PRD 3.2: "Attempting to modify a non-`ACTIVE` entity is rejected with
    `ERR_ENTITY_NOT_ACTIVE`."

    Design: Corner/state_machines/dissolved_entity_terminal_lockdown
    """
    ctx = setup_base_entity(legal_name="Terminal Corp")
    entity = ctx["entity"]
    adopt_resolution(entity["id"], "AUTHORIZE_DISSOLUTION", {}, "2026-08-01")
    validate_success(api.commence_dissolution(entity["id"], SEC1))
    dissolved = validate_success(api.finalize_dissolution(entity["id"], SEC1))
    assert dissolved["status"] == "DISSOLVED"

    patch_response = api.patch_entity(entity["id"], {"legal_name": "Zombie Corp"}, SEC1)
    validate_error(patch_response, ApiErrorId.ERR_ENTITY_NOT_ACTIVE)

    commence_response = api.commence_dissolution(entity["id"], SEC1)
    validate_error(commence_response, ApiErrorId.ERR_ENTITY_NOT_ACTIVE)

    current = fetch_entity(entity["id"])
    assert current["status"] == "DISSOLVED", "DISSOLVED is terminal"
    assert current["legal_name"] == "Terminal Corp", "the rejected PATCH changed nothing"


def test_dissolution_blocked_by_open_qualification(api):
    """PRD 3.12: "This requires an `AUTHORIZE_DISSOLUTION` resolution in
    `ADOPTED` or `EFFECTIVE` status and requires every `ForeignQualification`
    of the entity to be in `WITHDRAWN` or `REVOKED` status; open qualifications
    are rejected with `ERR_OPEN_QUALIFICATIONS_EXIST`."

    Design: Corner/errors/dissolution_blocked_by_open_qualification
    """
    ctx = setup_entity_with_qualification(confirm=True)
    entity = ctx["entity"]
    adopt_resolution(entity["id"], "AUTHORIZE_DISSOLUTION", {}, "2026-08-01")

    response = api.commence_dissolution(entity["id"], SEC1)
    validate_error(response, ApiErrorId.ERR_OPEN_QUALIFICATIONS_EXIST)

    current = fetch_entity(entity["id"])
    assert current["status"] == "ACTIVE"


def test_remove_officer_effective_cascade(api):
    """PRD 3.5: "When a `REMOVE_OFFICER` resolution becomes `EFFECTIVE`, the
    referenced appointment transitions from `APPOINTED` to `REMOVED` with
    `end_date` set to the resolution's `effective_date`. The same grant cascade
    applies."
    PRD 3.5: "Resignation transitions the appointment from `APPOINTED` to
    `RESIGNED`, sets `end_date` to the current logical date, and triggers the
    grant cascade described in §3.8."

    Design: Corner/state_machines/remove_officer_effective_cascade
    """
    ctx = setup_base_entity(legal_name="Removal Corp")
    entity = ctx["entity"]
    officer = create_officer()
    appointment = appoint_officer(entity["id"], officer["id"])
    grant = create_grant(entity["id"], officer["id"])

    adopt_resolution(
        entity["id"], "REMOVE_OFFICER", {"appointment_id": appointment["id"]}, "2026-08-01"
    )
    run_sweep()

    current = validate_success(api.get_officer_appointment(appointment["id"], SEC1))
    assert current["status"] == "REMOVED"
    assert current["end_date"] == "2026-08-01", "end_date is the resolution's effective_date"

    revoked = validate_success(api.get_signature_grant(grant["id"], SEC1))
    assert revoked["status"] == "REVOKED", "officer-exit cascade revokes the grant"

    event_types = list_event_types(entity["id"])
    assert "OFFICER_REMOVED" in event_types
    assert "GRANT_REVOKED" in event_types


def _setup_dissolution_cascade():
    """ACTIVE entity with two appointed officers, a direct grant on the first
    and a delegated grant (from it) on the second, plus an ADOPTED
    AUTHORIZE_DISSOLUTION resolution."""
    ctx = setup_base_entity(legal_name="Winddown Corp")
    entity = ctx["entity"]
    o1 = create_officer(full_name="Olivia Ortiz", email="oo@example.com")
    o2 = create_officer(full_name="CFO Carl", email="carl@example.com")
    appoint_officer(entity["id"], o1["id"], office_title="PRESIDENT")
    appoint_officer(entity["id"], o2["id"], office_title="CFO")
    g1 = create_grant(entity["id"], o1["id"], max_amount_cents=100000)
    g2 = create_grant(
        entity["id"],
        o2["id"],
        max_amount_cents=80000,
        effective_date="2026-03-01",
        expiry_date="2026-12-31",
        delegated_from_grant_id=g1["id"],
    )
    adopt_resolution(entity["id"], "AUTHORIZE_DISSOLUTION", {}, "2026-08-01")
    return ctx, o1, o2, g1, g2


def test_dissolution_cascade_removes_appointments(api):
    """PRD 3.12: "Upon finalization, `dissolved_date` is set to the current
    logical date, every `APPOINTED` appointment transitions to `REMOVED` with
    `end_date` set, every grant of those officers transitions to `REVOKED`,
    delegated grants are revoked, a `ComplianceEvent` of type
    `DISSOLUTION_COMPLETED` is appended, posture is recomputed, and the
    entity's `version` increments."
    PRD 3.12: "Commencement withdraws all `SCHEDULED` and `PREPARED` filings,
    appends a `ComplianceEvent` of type `DISSOLUTION_COMMENCED`, and increments
    the entity's `version`."

    Design: Difficulty/transitive_cascade/dissolution_compensation_cascade
    """
    ctx, o1, o2, g1, g2 = _setup_dissolution_cascade()
    entity = ctx["entity"]

    validate_success(api.commence_dissolution(entity["id"], SEC1))
    filings = list_filings(entity["id"])
    assert all(f["status"] == "WITHDRAWN" for f in filings), (
        "commencement cancels the future obligations, clearing the finalize gate"
    )

    dissolved = validate_success(api.finalize_dissolution(entity["id"], SEC1))
    assert dissolved["status"] == "DISSOLVED"
    assert dissolved["dissolved_date"] == "2026-08-01", "current logical date"

    for officer in (o1, o2):
        appointment = find_officer_appointment(entity["id"], officer["id"])
        assert appointment["status"] == "REMOVED"
        assert appointment["end_date"] == "2026-08-01"


def test_dissolution_cascade_revokes_direct_and_delegated_grants(api):
    """PRD 2.8: "Dissolving an entity revokes its officer appointments, then
    revokes the signature grants of those officers, then revokes any delegated
    grants. ... Every such cascade appends a `ComplianceEvent` to the entity's
    audit trail and increments the entity's `version`."
    PRD 3.12: "every grant of those officers transitions to `REVOKED`,
    delegated grants are revoked, a `ComplianceEvent` of type
    `DISSOLUTION_COMPLETED` is appended"

    Design: Difficulty/transitive_cascade/dissolution_compensation_cascade
    """
    ctx, o1, o2, g1, g2 = _setup_dissolution_cascade()
    entity = ctx["entity"]

    validate_success(api.commence_dissolution(entity["id"], SEC1))
    validate_success(api.finalize_dissolution(entity["id"], SEC1))

    for grant in (g1, g2):
        current = validate_success(api.get_signature_grant(grant["id"], SEC1))
        assert current["status"] == "REVOKED", (
            f"grant {grant['id']} revoked by the dissolution cascade"
        )

    event_types = list_event_types(entity["id"])
    assert "DISSOLUTION_COMMENCED" in event_types
    assert "DISSOLUTION_COMPLETED" in event_types
    assert event_types.count("OFFICER_REMOVED") == 2, "one event per removed appointment"
    assert event_types.count("GRANT_REVOKED") == 2, "one event per revoked grant"
